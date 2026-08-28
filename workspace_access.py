"""Workspace module registry and permission helpers for Hotel Bell Elite."""

import functools

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
    {"key": "back_office_receipt", "label": "Back Office Receipt"},
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

_POS_SUBMODULES = (
    {"key": "tables", "label": "Tables"},
    {"key": "invoice", "label": "POS"},
    {"key": "invoice_ledger", "label": "Invoice Ledger"},
    {"key": "kot_cancellation", "label": "KOT Cancellation"},
    {"key": "sales_update", "label": "Sales Update"},
    {"key": "menu", "label": "Menu"},
    {"key": "settings", "label": "Settings"},
)

_HOTEL_SUBMODULES = (
    {"key": "reservations", "label": "Reservations"},
    {"key": "rooms", "label": "Rooms"},
    {"key": "invoice_ledger", "label": "Invoice Ledger"},
    {"key": "credit", "label": "Credit"},
    {"key": "sales_update", "label": "Sales Update"},
    {"key": "settings", "label": "Settings"},
)

_COMMUNICATION_HUB_SUBMODULES = (
    {"key": "inbox", "label": "Inbox"},
    {"key": "promotion", "label": "Promotion"},
)

_MASTER_SUBMODULES = (
    {"key": "customer", "label": "Customer Master"},
    {"key": "agency", "label": "Agency Master"},
    {"key": "category", "label": "Category Master"},
)

_REPORTS_SUBMODULES = (
    {"key": "hotel_sales", "label": "Hotel Sales"},
    {"key": "agency_billing", "label": "Agency Ledger"},
    {"key": "manager_insight", "label": "Manager Insight"},
    {"key": "meal_plan", "label": "Meal Plan"},
    {"key": "kot", "label": "KOT"},
    {"key": "restaurant_sales", "label": "Sales - Restaurant & Bar"},
    {"key": "menu_sales", "label": "Menu Insights"},
    {"key": "customer_insights", "label": "Customer Insights"},
    {
        "key": "gst",
        "label": "GST",
        "children": (
            {"key": "gst_hotel", "label": "Hotel"},
            {"key": "gst_fnb", "label": "Restaurant & Bar"},
        ),
    },
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
_REPORTS_SUBMODULES_FLAT = _flatten_submodules(_REPORTS_SUBMODULES)
_GST_REPORT_KEYS = frozenset({"gst", "gst_hotel", "gst_fnb"})

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
        "permission_scope": "point_of_sale",
        "permission_field": "point_of_sale_modules",
        "permission_children": _POS_SUBMODULES,
    },
    {
        "key": "point_of_sale_bar",
        "label": "Bar",
        "permission_scope": "point_of_sale_bar",
        "permission_field": "point_of_sale_bar_modules",
        "permission_children": _POS_SUBMODULES,
    },
    {
        "key": "hotel_rooms",
        "label": "Hotel",
        "permission_scope": "hotel_rooms",
        "permission_field": "hotel_rooms_modules",
        "permission_children": _HOTEL_SUBMODULES,
    },
    {
        "key": "communication_hub",
        "label": "Communication Hub",
        "permission_scope": "communication_hub",
        "permission_field": "communication_hub_modules",
        "permission_children": _COMMUNICATION_HUB_SUBMODULES,
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
        "permission_scope": "master",
        "permission_field": "master_modules",
        "permission_children": _MASTER_SUBMODULES,
    },
    {
        "key": "reports",
        "label": "Report",
        "permission_scope": "reports",
        "permission_field": "reports_modules",
        "permission_children": _REPORTS_SUBMODULES,
    },
    {
        "key": "settings",
        "label": "Settings",
        # Workspace settings hub Overview only; outlet settings live under Restaurant/Bar/Hotel.
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
        "label": "Cancellation",
        # Module-level grant: cancel unsettled POS and Hotel invoices.
        "permission_scope": None,
        "permission_field": None,
        "permission_children": (),
    },
    {
        "key": "edit_access",
        "label": "Edit",
        # Module-level grant: reopen/edit unsettled POS and Hotel invoices.
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
_SUPER_ADMIN_ONLY_DASHBOARD_KEYS = frozenset(
    {"approval", "cancellation_access", "edit_access"}
)
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
_POS_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _POS_SUBMODULES
}
_HOTEL_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _HOTEL_SUBMODULES
}
_COMMUNICATION_HUB_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _COMMUNICATION_HUB_SUBMODULES
}
_MASTER_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _MASTER_SUBMODULES
}
_REPORTS_SUBMODULE_LABELS = {
    item["key"]: item["label"] for item in _REPORTS_SUBMODULES_FLAT
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
            "Kitchen-sent lines can be edited until Generate Invoice; "
            "after that, Restaurant → KOT Cancellation is required to "
            "reduce or cancel Kitchen Order Tokens on Tables."
        ),
    },
    "point_of_sale_bar": {
        "icon": "receipt",
        "description": (
            "Bar counter billing and invoice workspace. "
            "Kitchen-sent lines can be edited until Generate Invoice; "
            "after that, Bar → KOT Cancellation is required to "
            "reduce or cancel Kitchen Order Tokens on Tables."
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
            "Cancel unsettled POS and Hotel invoices. "
            "Only a Super Administrator can grant this module to a role. "
            "KOT reduce/cancel on Tables is granted separately under "
            "Restaurant or Bar → KOT Cancellation."
        ),
    },
    "edit_access": {
        "icon": "pencil",
        "description": (
            "Edit room invoice folio charges (rates, discounts, custom lines) "
            "and reopen unsettled POS or Hotel invoices. "
            "Only a Super Administrator can grant this module to a role."
        ),
    },
}

# Point of Sale workspace routes (Tables + POS + Invoice Ledger + Menu + Settings). Not Sales Analytics.
_POINT_OF_SALE_ENDPOINT_GROUPS = {
    "tables": {
        "point_of_sale",
        "point_of_sale_api_floor",
        "point_of_sale_api_kot_tokens",
        "point_of_sale_api_kot_tokens_reduce",
    },
    "invoice": {
        "point_of_sale_invoice",
        "point_of_sale_api_invoices_save",
        "point_of_sale_api_invoice_detail",
        "point_of_sale_api_invoice_delete",
        "point_of_sale_api_invoice_reopen_edit",
        "point_of_sale_api_customers",
        "point_of_sale_api_invoice_settle",
        "point_of_sale_api_invoices_settle_selected",
        "point_of_sale_api_hotel_rooms_occupied",
        "point_of_sale_api_kot_tokens",
        "point_of_sale_api_kot_tokens_reduce",
        "point_of_sale_api_menu_products",
    },
    "invoice_ledger": {
        "point_of_sale_invoice_ledger",
        "export_pos_invoice_ledger_report",
        "point_of_sale_api_invoice_detail",
        "point_of_sale_api_invoice_delete",
        "point_of_sale_api_invoice_reopen_edit",
        "point_of_sale_api_invoice_settle",
        "point_of_sale_api_invoices_settle_selected",
    },
    "sales_update": {
        "point_of_sale_sales_update",
    },
    "menu": {
        "point_of_sale_menu",
        "point_of_sale_menu_export",
        "point_of_sale_api_menu_categories",
        "point_of_sale_api_menu_category_delete",
        "point_of_sale_api_menu_items",
        "point_of_sale_api_menu_items_bulk",
        "point_of_sale_api_menu_items_bulk_template",
        "point_of_sale_api_menu_item_delete",
        "point_of_sale_api_menu_products",
    },
    "settings": {
        "point_of_sale_settings",
        "point_of_sale_api_settings",
    },
}
_POINT_OF_SALE_ENDPOINTS = set().union(*_POINT_OF_SALE_ENDPOINT_GROUPS.values())

_POINT_OF_SALE_BAR_ENDPOINT_GROUPS = {
    "tables": {
        "bar_point_of_sale",
        "bar_point_of_sale_api_floor",
        "bar_point_of_sale_api_kot_tokens",
        "bar_point_of_sale_api_kot_tokens_reduce",
    },
    "invoice": {
        "bar_point_of_sale_invoice",
        "bar_point_of_sale_api_invoices_save",
        "bar_point_of_sale_api_invoice_detail",
        "bar_point_of_sale_api_invoice_delete",
        "bar_point_of_sale_api_invoice_reopen_edit",
        "bar_point_of_sale_api_customers",
        "bar_point_of_sale_api_invoice_settle",
        "bar_point_of_sale_api_invoices_settle_selected",
        "bar_point_of_sale_api_hotel_rooms_occupied",
        "bar_point_of_sale_api_kot_tokens",
        "bar_point_of_sale_api_kot_tokens_reduce",
        "bar_point_of_sale_api_menu_products",
    },
    "invoice_ledger": {
        "bar_point_of_sale_invoice_ledger",
        "bar_export_pos_invoice_ledger_report",
        "bar_point_of_sale_api_invoice_detail",
        "bar_point_of_sale_api_invoice_delete",
        "bar_point_of_sale_api_invoice_reopen_edit",
        "bar_point_of_sale_api_invoice_settle",
        "bar_point_of_sale_api_invoices_settle_selected",
    },
    "sales_update": {
        "bar_point_of_sale_sales_update",
    },
    "menu": {
        "bar_point_of_sale_menu",
        "bar_point_of_sale_menu_export",
        "bar_point_of_sale_api_menu_categories",
        "bar_point_of_sale_api_menu_category_delete",
        "bar_point_of_sale_api_menu_items",
        "bar_point_of_sale_api_menu_items_bulk",
        "bar_point_of_sale_api_menu_items_bulk_template",
        "bar_point_of_sale_api_menu_item_delete",
        "bar_point_of_sale_api_menu_products",
    },
    "settings": {
        "bar_point_of_sale_settings",
        "bar_point_of_sale_api_settings",
    },
}
_POINT_OF_SALE_BAR_ENDPOINTS = set().union(*_POINT_OF_SALE_BAR_ENDPOINT_GROUPS.values())

_HOTEL_ROOMS_ENDPOINT_GROUPS = {
    "reservations": {
        "hotel_reservations",
        "hotel_reservations_api",
        "hotel_reservation_detail_api",
        "hotel_reservation_assign_api",
        "hotel_guest_lookup_api",
        "hotel_customers_api",
        "hotel_id_document_upload",
        "hotel_id_document_file",
        "hotel_id_document_file_view",
    },
    "rooms": {
        "hotel_rooms",
        "hotel_rooms_api",
        "hotel_room_detail",
        "hotel_room_detail_api",
        "hotel_room_invoice_page",
        "hotel_guest_lookup_api",
        "hotel_customers_api",
        "hotel_id_document_upload",
        "hotel_id_document_file",
        "hotel_id_document_file_view",
    },
    "invoice_ledger": {
        "hotel_invoice_ledger",
        "hotel_invoice_ledger_export",
        "hotel_room_transfer_invoices",
        "hotel_room_transfer_invoices_export",
        "hotel_invoice_ledger_api",
        "hotel_invoice_ledger_settle_api",
        "hotel_invoice_ledger_settle_selected_api",
        "hotel_invoice_ledger_cancel_api",
        "hotel_invoice_ledger_reopen_edit_api",
        "hotel_invoice_ledger_edit_page",
        "hotel_invoice_ledger_edit_api",
    },
    "credit": {
        "hotel_credit",
        "export_hotel_credit_report",
        "create_hotel_credit_payment",
        "delete_hotel_credit_payment",
        "hotel_credit_payment_detail",
        "hotel_credit_pending_receipts",
    },
    "sales_update": {
        "hotel_sales_update",
    },
    "settings": {
        "hotel_settings",
        "hotel_settings_api",
    },
}
_HOTEL_ROOMS_ENDPOINTS = set().union(*_HOTEL_ROOMS_ENDPOINT_GROUPS.values())

_MAIN_DASHBOARD_ENDPOINTS = {
    "main_dashboard",
}

_COMMUNICATION_HUB_ENDPOINT_GROUPS = {
    "inbox": {
        "communication_hub",
        "communication_hub_api_conversations",
        "communication_hub_api_conversation_create",
        "communication_hub_api_conversation_delete",
        "communication_hub_api_messages",
        "communication_hub_api_message_send",
    },
    "promotion": {
        "communication_hub_promotion",
        "communication_hub_api_promotion_templates",
        "communication_hub_api_promotion_sample",
        "communication_hub_api_promotion_preview",
        "communication_hub_api_promotion_send",
    },
}
_COMMUNICATION_HUB_ENDPOINTS = set().union(*_COMMUNICATION_HUB_ENDPOINT_GROUPS.values())

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
        "stores_api_indent_catalog",
        "stores_api_indent_create",
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

_MASTER_ENDPOINT_GROUPS = {
    "customer": {
        "customer_master",
        "save_customer",
        "delete_customer",
        "export_customer_report",
    },
    "agency": {
        "agency_master",
        "save_agency",
        "delete_agency",
        "export_agency_report",
        "create_agency",
        "list_agencies_api",
    },
    "category": {
        "category_master",
        "save_category_master",
        "delete_category_master",
    },
}
_MASTER_ENDPOINTS = set().union(*_MASTER_ENDPOINT_GROUPS.values()) | {"master"}

_REPORTS_ENDPOINT_GROUPS = {
    "hotel_sales": {
        "sales_report_hotel",
        "sales_report_hotel_export",
    },
    "agency_billing": {
        "sales_report_agency_billing",
        "sales_report_agency_billing_export",
    },
    "manager_insight": {
        "sales_report_manager_insight",
        "sales_report_manager_insight_export",
    },
    "meal_plan": {
        "sales_report_meal_plan",
        "sales_report_meal_plan_export",
    },
    "kot": {
        "sales_report_kot",
        "sales_report_kot_export",
    },
    "restaurant_sales": {
        "sales_report_restaurant",
        "sales_report_restaurant_export",
        "sales_report_bar",
        "sales_report_bar_export",
    },
    "menu_sales": {
        "sales_report_menu",
        "sales_report_menu_export",
    },
    "customer_insights": {
        "sales_report_customer_insights",
        "sales_report_customer_insights_export",
    },
    "gst_hotel": {
        "gst_hotel_report",
        "gst_hotel_report_export",
    },
    "gst_fnb": {
        "gst_fnb_report",
        "gst_fnb_report_export",
    },
}
_REPORTS_ENDPOINTS = set().union(*_REPORTS_ENDPOINT_GROUPS.values()) | {"reports"}

_SETTINGS_ENDPOINTS = {
    "settings",
}

_PUBLIC_ENDPOINTS = {
    "index",
    "login",
    "login_get",
    "login_captcha",
    "login_resend_unlock",
    "unlock_account",
    "logout",
    "static",
    "favicon",
    "whatsapp_webhook",
    "robots_txt",
    "sitemap_xml",
    "mobile_ota_manifest",
    "mobile_ota_apk",
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
        "sales_update_add_staff_credit",
        "sales_update_edit_staff_credit",
        "sales_update_delete_staff_credit",
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
    "back_office_receipt": {
        "back_office_receipt",
        "back_office_receipt_add",
        "back_office_receipt_edit",
        "back_office_receipt_delete",
        "export_back_office_receipt_report",
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
        "mobile_payroll_employees",
        "mobile_payroll_employee_detail",
        "mobile_payroll_employee_create",
        "mobile_payroll_employee_update",
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
        "mobile_payroll_attendance",
        "mobile_payroll_attendance_detail",
        "mobile_payroll_attendance_mark",
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
        "mobile_payroll_credits",
        "mobile_payroll_credit_create",
    },
    "tips": {
        "sales_update_tips_page",
        "export_tips_report",
        "tips_incentive_payout",
        "sales_update_tips_delete_employee",
        "sales_update_tips_employee_lines",
        "sales_update_edit_tip",
        "mobile_payroll_tips",
        "mobile_payroll_tips_add",
        "mobile_payroll_tips_incentive",
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


@functools.lru_cache(maxsize=1)
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


@functools.lru_cache(maxsize=1)
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
    return {
        "dashboard": set(),
        "sales_analytics": set(),
        "user_access": set(),
        "payroll": set(),
        "accounts": set(),
        "stores": set(),
        "point_of_sale": set(),
        "point_of_sale_bar": set(),
        "hotel_rooms": set(),
        "communication_hub": set(),
        "master": set(),
        "reports": set(),
    }


_PERMISSION_SCOPE_ATTRS = {
    "dashboard": "dashboard_access",
    "sales_analytics": "sales_analytics_access",
    "user_access": "user_access",
    "payroll": "payroll_access",
    "accounts": "accounts_access",
    "stores": "stores_access",
    "point_of_sale": "point_of_sale_access",
    "point_of_sale_bar": "point_of_sale_bar_access",
    "hotel_rooms": "hotel_rooms_access",
    "communication_hub": "communication_hub_access",
    "master": "master_access",
    "reports": "reports_access",
}


def _permission_sets_from_rows(rows):
    sets = _empty_permission_sets()
    for row in rows:
        scope = (row["scope"] or "").strip()
        item_key = (row["item_key"] or "").strip()
        if scope == "dashboard" and item_key == "sales_update":
            # Legacy key from earlier builds.
            sets["dashboard"].add("sales_analytics")
        elif scope in sets and item_key:
            sets[scope].add(item_key)
    return sets


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
    for scope, attr in _PERMISSION_SCOPE_ATTRS.items():
        target[attr] = set(permission_sets.get(scope) or ())


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
    if module_key == "point_of_sale" and user.get("point_of_sale_access", set()):
        return True
    if module_key == "point_of_sale_bar" and user.get("point_of_sale_bar_access", set()):
        return True
    if module_key == "hotel_rooms" and user.get("hotel_rooms_access", set()):
        return True
    if module_key == "communication_hub" and user.get("communication_hub_access", set()):
        return True
    if module_key == "master" and user.get("master_access", set()):
        return True
    if module_key == "reports" and user.get("reports_access", set()):
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


def _scoped_access_keys(user, *, attr, dashboard_key, all_keys):
    """Resolved page keys for a scoped module (legacy parent grant = all pages)."""
    if not user:
        return set()
    if user.get("is_admin"):
        return set(all_keys)
    access = set(user.get(attr, set()) or set())
    if access:
        return access
    if dashboard_key in user.get("dashboard_access", set()):
        return set(all_keys)
    return set()


def user_can_access_point_of_sale_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in _scoped_access_keys(
        user,
        attr="point_of_sale_access",
        dashboard_key="point_of_sale",
        all_keys={item["key"] for item in _POS_SUBMODULES},
    )


def user_can_access_point_of_sale_bar_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in _scoped_access_keys(
        user,
        attr="point_of_sale_bar_access",
        dashboard_key="point_of_sale_bar",
        all_keys={item["key"] for item in _POS_SUBMODULES},
    )


def user_can_access_hotel_rooms_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in _scoped_access_keys(
        user,
        attr="hotel_rooms_access",
        dashboard_key="hotel_rooms",
        all_keys={item["key"] for item in _HOTEL_SUBMODULES},
    )


def user_can_access_communication_hub_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in _scoped_access_keys(
        user,
        attr="communication_hub_access",
        dashboard_key="communication_hub",
        all_keys={item["key"] for item in _COMMUNICATION_HUB_SUBMODULES},
    )


def user_can_access_master_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in _scoped_access_keys(
        user,
        attr="master_access",
        dashboard_key="master",
        all_keys={item["key"] for item in _MASTER_SUBMODULES},
    )


def _reports_all_keys():
    return {item["key"] for item in _REPORTS_SUBMODULES_FLAT}


def _reports_access_keys(user):
    """Resolved Report page keys. GST defaults ON for existing report users."""
    unlocked = _scoped_access_keys(
        user,
        attr="reports_access",
        dashboard_key="reports",
        all_keys=_reports_all_keys(),
    )
    if unlocked:
        return set(unlocked) | _GST_REPORT_KEYS
    return unlocked


def user_can_access_reports_submodule(user, submodule_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    return submodule_key in _reports_access_keys(user)


def user_can_access_supplier_master(user):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if user_can_access_accounts_submodule(user, "supplier_master"):
        return True
    return "suppliers" in user.get("sales_analytics_access", set())


def user_can_access_customer_master(user):
    """Customer Master is available to Master hub and Restaurant/Bar users."""
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if user_can_access_master_submodule(user, "customer"):
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
    if user_can_access_master_submodule(user, "agency"):
        return True
    if user_can_access_dashboard(user, "hotel_rooms"):
        return True
    return False


def user_can_access_category_master(user):
    """Category Master via Master hub or Restaurant/Bar Menu."""
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if user_can_access_master_submodule(user, "category"):
        return True
    if user_can_access_point_of_sale_submodule(user, "menu"):
        return True
    if user_can_access_point_of_sale_bar_submodule(user, "menu"):
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
    if user.get("point_of_sale_access", set()):
        dashboard_access.add("point_of_sale")
    if user.get("point_of_sale_bar_access", set()):
        dashboard_access.add("point_of_sale_bar")
    if user.get("hotel_rooms_access", set()):
        dashboard_access.add("hotel_rooms")
    if user.get("communication_hub_access", set()):
        dashboard_access.add("communication_hub")
    if user.get("master_access", set()):
        dashboard_access.add("master")
    if user.get("reports_access", set()):
        dashboard_access.add("reports")
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


def point_of_sale_access_list(user):
    if not user:
        return []
    unlocked = _scoped_access_keys(
        user,
        attr="point_of_sale_access",
        dashboard_key="point_of_sale",
        all_keys={item["key"] for item in _POS_SUBMODULES},
    )
    return [item["key"] for item in _POS_SUBMODULES if item["key"] in unlocked]


def point_of_sale_bar_access_list(user):
    if not user:
        return []
    unlocked = _scoped_access_keys(
        user,
        attr="point_of_sale_bar_access",
        dashboard_key="point_of_sale_bar",
        all_keys={item["key"] for item in _POS_SUBMODULES},
    )
    return [item["key"] for item in _POS_SUBMODULES if item["key"] in unlocked]


def hotel_rooms_access_list(user):
    if not user:
        return []
    unlocked = _scoped_access_keys(
        user,
        attr="hotel_rooms_access",
        dashboard_key="hotel_rooms",
        all_keys={item["key"] for item in _HOTEL_SUBMODULES},
    )
    return [item["key"] for item in _HOTEL_SUBMODULES if item["key"] in unlocked]


def communication_hub_access_list(user):
    if not user:
        return []
    unlocked = _scoped_access_keys(
        user,
        attr="communication_hub_access",
        dashboard_key="communication_hub",
        all_keys={item["key"] for item in _COMMUNICATION_HUB_SUBMODULES},
    )
    return [item["key"] for item in _COMMUNICATION_HUB_SUBMODULES if item["key"] in unlocked]


def master_access_list(user):
    if not user:
        return []
    unlocked = _scoped_access_keys(
        user,
        attr="master_access",
        dashboard_key="master",
        all_keys={item["key"] for item in _MASTER_SUBMODULES},
    )
    return [item["key"] for item in _MASTER_SUBMODULES if item["key"] in unlocked]


def reports_access_list(user):
    if not user:
        return []
    unlocked = _reports_access_keys(user)
    return [item["key"] for item in _REPORTS_SUBMODULES_FLAT if item["key"] in unlocked]


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
    bare = endpoint.split(".", 1)[1] if endpoint and "." in str(endpoint) else endpoint
    for key, endpoints in _PAYROLL_ENDPOINT_GROUPS.items():
        if endpoint in endpoints or bare in endpoints:
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


def _endpoint_submodules_from_groups(endpoint, groups):
    matches = []
    for key, endpoints in groups.items():
        if endpoint in endpoints:
            matches.append(key)
    return matches


def get_endpoint_point_of_sale_submodules(endpoint):
    return _endpoint_submodules_from_groups(endpoint, _POINT_OF_SALE_ENDPOINT_GROUPS)


def get_endpoint_point_of_sale_bar_submodules(endpoint):
    return _endpoint_submodules_from_groups(endpoint, _POINT_OF_SALE_BAR_ENDPOINT_GROUPS)


def get_endpoint_hotel_rooms_submodules(endpoint):
    return _endpoint_submodules_from_groups(endpoint, _HOTEL_ROOMS_ENDPOINT_GROUPS)


def get_endpoint_communication_hub_submodule(endpoint):
    matches = _endpoint_submodules_from_groups(endpoint, _COMMUNICATION_HUB_ENDPOINT_GROUPS)
    return matches[0] if matches else None


def get_endpoint_master_submodule(endpoint):
    matches = _endpoint_submodules_from_groups(endpoint, _MASTER_ENDPOINT_GROUPS)
    return matches[0] if matches else None


def get_endpoint_reports_submodule(endpoint):
    matches = _endpoint_submodules_from_groups(endpoint, _REPORTS_ENDPOINT_GROUPS)
    return matches[0] if matches else None


def _user_can_access_any_submodule(user, submodules, checker):
    if not submodules:
        return True
    if len(submodules) == 1:
        return checker(user, submodules[0])
    return any(checker(user, key) for key in submodules)


def user_can_access_endpoint_point_of_sale(user, endpoint):
    return _user_can_access_any_submodule(
        user,
        get_endpoint_point_of_sale_submodules(endpoint),
        user_can_access_point_of_sale_submodule,
    )


def user_can_access_endpoint_point_of_sale_bar(user, endpoint):
    return _user_can_access_any_submodule(
        user,
        get_endpoint_point_of_sale_bar_submodules(endpoint),
        user_can_access_point_of_sale_bar_submodule,
    )


def user_can_access_endpoint_hotel_rooms(user, endpoint):
    return _user_can_access_any_submodule(
        user,
        get_endpoint_hotel_rooms_submodules(endpoint),
        user_can_access_hotel_rooms_submodule,
    )


def user_can_access_endpoint_communication_hub(user, endpoint):
    submodule = get_endpoint_communication_hub_submodule(endpoint)
    if not submodule:
        return True
    return user_can_access_communication_hub_submodule(user, submodule)


def user_can_access_endpoint_master(user, endpoint):
    submodule = get_endpoint_master_submodule(endpoint)
    if not submodule:
        return True
    if submodule == "customer":
        return user_can_access_customer_master(user)
    if submodule == "agency":
        return user_can_access_agency_master(user)
    if submodule == "category":
        return user_can_access_category_master(user)
    return user_can_access_master_submodule(user, submodule)


def user_can_access_endpoint_reports(user, endpoint):
    submodule = get_endpoint_reports_submodule(endpoint)
    if not submodule:
        return True
    return user_can_access_reports_submodule(user, submodule)


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


def user_can_cancel_invoices(user):
    """True when the user may cancel unsettled POS or Hotel invoices.

    Granted via the Cancellation module (administrators include all modules).
    """
    return user_can_access_dashboard(user, "cancellation_access")


def user_can_edit_kot_sent_lines(user, outlet=None):
    """True when the user may reduce/cancel kitchen-sent KOT lines on Tables.

    Granted via Restaurant or Bar → KOT Cancellation (administrators include all).
    Create Invoice still allows line edits until Generate Invoice without this.
    """
    if not user:
        return False
    if user.get("is_admin"):
        return True
    outlet_key = str(outlet or "").strip().lower()
    if outlet_key in ("bar", "point_of_sale_bar"):
        return user_can_access_point_of_sale_bar_submodule(user, "kot_cancellation")
    if outlet_key in ("restaurant", "point_of_sale"):
        return user_can_access_point_of_sale_submodule(user, "kot_cancellation")
    return user_can_access_point_of_sale_submodule(
        user, "kot_cancellation"
    ) or user_can_access_point_of_sale_bar_submodule(user, "kot_cancellation")


def user_can_edit_unsettled_invoices(user):
    """True when the user may edit hotel/POS invoice folio charges and reopen invoices.

    Granted via the Edit module (administrators include all modules).
    """
    return user_can_access_dashboard(user, "edit_access")


def user_can_approve_transactions(user):
    """True when the user may clear/verify/revert settlement transactions
    and open Indent Approvals.

    Granted via the Approval module (administrators include all modules).
    Covers Credit Payment Clear Payment / Revert, Purchase Verification
    Verify / Approve / Revert, and Stores Indent Approvals. View access to
    settlement pages is separate.
    """
    return user_can_access_dashboard(user, "approval")


def mobile_module_access(user):
    """Boolean flags for mobile / preview nav tiles (same rules as web sidebar).

    Keys match mobile screen ids used by the HTML preview and Kivy shell.
    """
    if not user:
        return {
            "home": False,
            "main_dashboard": False,
            "indent_approvals": False,
            "indent_request": False,
            "pos": False,
            "kot": False,
            "pos_bar": False,
            "kot_bar": False,
            "approvals": False,
            "purchase_ledger": False,
            "cash_ledger": False,
            "payroll_employee": False,
            "payroll_attendance": False,
            "payroll_credit": False,
            "payroll_tips": False,
            "can_approve": False,
            "is_admin": False,
        }

    pos_invoice = user_can_access_point_of_sale_submodule(user, "invoice")
    pos_tables = user_can_access_point_of_sale_submodule(user, "tables")
    bar_invoice = user_can_access_point_of_sale_bar_submodule(user, "invoice")
    bar_tables = user_can_access_point_of_sale_bar_submodule(user, "tables")
    can_approve = user_can_approve_transactions(user)

    return {
        "home": True,
        "main_dashboard": user_can_access_dashboard(user, "main_dashboard"),
        "indent_approvals": can_approve,
        "indent_request": user_can_access_stores_submodule(user, "indent"),
        "pos": pos_invoice,
        "kot": bool(pos_invoice or pos_tables),
        "pos_bar": bar_invoice,
        "kot_bar": bool(bar_invoice or bar_tables),
        "approvals": user_can_access_accounts_submodule(user, "purchase_verification"),
        "purchase_ledger": user_can_access_accounts_submodule(user, "purchase_ledger"),
        "cash_ledger": user_can_access_accounts_submodule(user, "cash_ledger"),
        "payroll_employee": user_can_access_payroll_submodule(user, "employee"),
        "payroll_attendance": user_can_access_payroll_submodule(user, "attendance"),
        "payroll_credit": user_can_access_payroll_submodule(user, "credit"),
        "payroll_tips": user_can_access_payroll_submodule(user, "tips"),
        "can_approve": can_approve,
        "is_admin": bool(user.get("is_admin")),
    }


def _normalize_permission_modules(
    dashboard_modules,
    sales_analytics_modules=None,
    user_access_modules=None,
    payroll_modules=None,
    accounts_modules=None,
    stores_modules=None,
    point_of_sale_modules=None,
    point_of_sale_bar_modules=None,
    hotel_rooms_modules=None,
    communication_hub_modules=None,
    master_modules=None,
    reports_modules=None,
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
    point_of_sale_modules = sorted({
        module
        for module in (point_of_sale_modules or [])
        if module in _POS_SUBMODULE_LABELS
    })
    point_of_sale_bar_modules = sorted({
        module
        for module in (point_of_sale_bar_modules or [])
        if module in _POS_SUBMODULE_LABELS
    })
    hotel_rooms_modules = sorted({
        module
        for module in (hotel_rooms_modules or [])
        if module in _HOTEL_SUBMODULE_LABELS
    })
    communication_hub_modules = sorted({
        module
        for module in (communication_hub_modules or [])
        if module in _COMMUNICATION_HUB_SUBMODULE_LABELS
    })
    master_modules = sorted({
        module
        for module in (master_modules or [])
        if module in _MASTER_SUBMODULE_LABELS
    })
    reports_modules = sorted({
        module
        for module in (reports_modules or [])
        if module in _REPORTS_SUBMODULE_LABELS
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
    if point_of_sale_modules and "point_of_sale" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["point_of_sale"]))
    if point_of_sale_bar_modules and "point_of_sale_bar" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["point_of_sale_bar"]))
    if hotel_rooms_modules and "hotel_rooms" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["hotel_rooms"]))
    if communication_hub_modules and "communication_hub" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["communication_hub"]))
    if master_modules and "master" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["master"]))
    if reports_modules and "reports" not in dashboard_modules:
        dashboard_modules = sorted(set(dashboard_modules + ["reports"]))

    return {
        "dashboard": dashboard_modules,
        "sales_analytics": sales_analytics_modules,
        "user_access": user_access_modules,
        "payroll": payroll_modules,
        "accounts": accounts_modules,
        "stores": stores_modules,
        "point_of_sale": point_of_sale_modules,
        "point_of_sale_bar": point_of_sale_bar_modules,
        "hotel_rooms": hotel_rooms_modules,
        "communication_hub": communication_hub_modules,
        "master": master_modules,
        "reports": reports_modules,
    }


# Parent dashboard key for each child permission scope (form field → dashboard module).
_SCOPE_PARENT_DASHBOARD = {
    "sales_analytics": "sales_analytics",
    "user_access": "access_management",
    "payroll": "employee_payroll",
    "accounts": "accounts",
    "stores": "stores",
    "point_of_sale": "point_of_sale",
    "point_of_sale_bar": "point_of_sale_bar",
    "hotel_rooms": "hotel_rooms",
    "communication_hub": "communication_hub",
    "master": "master",
    "reports": "reports",
}


def _permission_insert_rows(normalized):
    rows = []
    dashboard_modules = normalized.get("dashboard") or []
    for module_key in dashboard_modules:
        rows.append(("dashboard", module_key))
    for scope, parent in _SCOPE_PARENT_DASHBOARD.items():
        if parent in dashboard_modules:
            for module_key in normalized.get(scope) or []:
                rows.append((scope, module_key))
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
    point_of_sale_modules=None,
    point_of_sale_bar_modules=None,
    hotel_rooms_modules=None,
    communication_hub_modules=None,
    master_modules=None,
    reports_modules=None,
):
    normalized = _normalize_permission_modules(
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
        point_of_sale_modules,
        point_of_sale_bar_modules,
        hotel_rooms_modules,
        communication_hub_modules,
        master_modules,
        reports_modules,
    )
    conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
    for scope, item_key in _permission_insert_rows(normalized):
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
    point_of_sale_modules=None,
    point_of_sale_bar_modules=None,
    hotel_rooms_modules=None,
    communication_hub_modules=None,
    master_modules=None,
    reports_modules=None,
):
    normalized = _normalize_permission_modules(
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
        stores_modules,
        point_of_sale_modules,
        point_of_sale_bar_modules,
        hotel_rooms_modules,
        communication_hub_modules,
        master_modules,
        reports_modules,
    )
    conn.execute("DELETE FROM access_role_permissions WHERE role_id = ?", (role_id,))
    for scope, item_key in _permission_insert_rows(normalized):
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
        "point_of_sale_labels": [
            _POS_SUBMODULE_LABELS[key] for key in point_of_sale_access_list(entity)
        ],
        "point_of_sale_bar_labels": [
            _POS_SUBMODULE_LABELS[key] for key in point_of_sale_bar_access_list(entity)
        ],
        "hotel_rooms_labels": [
            _HOTEL_SUBMODULE_LABELS[key] for key in hotel_rooms_access_list(entity)
        ],
        "communication_hub_labels": [
            _COMMUNICATION_HUB_SUBMODULE_LABELS[key]
            for key in communication_hub_access_list(entity)
        ],
        "master_labels": [
            _MASTER_SUBMODULE_LABELS[key] for key in master_access_list(entity)
        ],
        "reports_labels": [
            _REPORTS_SUBMODULE_LABELS[key] for key in reports_access_list(entity)
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
            perm_sets = _permission_sets_from_rows(perm_rows)
            set_role_permissions(
                conn,
                role_id,
                sorted(perm_sets["dashboard"]),
                sorted(perm_sets["sales_analytics"]),
                sorted(perm_sets["user_access"]),
                sorted(perm_sets["payroll"]),
                sorted(perm_sets["accounts"]),
                sorted(perm_sets["stores"]),
                point_of_sale_modules=sorted(perm_sets["point_of_sale"]),
                point_of_sale_bar_modules=sorted(perm_sets["point_of_sale_bar"]),
                hotel_rooms_modules=sorted(perm_sets["hotel_rooms"]),
                communication_hub_modules=sorted(perm_sets["communication_hub"]),
                master_modules=sorted(perm_sets["master"]),
                reports_modules=sorted(perm_sets["reports"]),
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
    elif password:
        complexity_error = auth_security.password_complexity_error(password)
        if complexity_error:
            errors.append(complexity_error)
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
    must_change_password=False,
):
    email = (email or "").strip()
    role = get_access_role(conn, role_id)
    is_admin = bool(role and role.get("is_admin"))
    force_change = 1 if must_change_password else 0
    if user_id:
        params = [username, full_name, email, int(is_admin), role_id]
        update_sql = (
            f"UPDATE users SET username = ?, full_name = ?, email = ?, is_admin = ?, "
            f"role_id = ?, is_active = 1, updated_at = {sql_now}"
        )
        if password:
            update_sql += ", password_hash = ?, must_change_password = ?"
            params.extend([auth_security.hash_password(password), force_change])
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, {sql_now}, {sql_now})""",
            (
                username,
                full_name,
                email,
                auth_security.hash_password(password),
                int(is_admin),
                role_id,
                (photo_path or "").strip() if photo_path is not None else "",
                force_change,
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
    point_of_sale_modules=None,
    point_of_sale_bar_modules=None,
    hotel_rooms_modules=None,
    communication_hub_modules=None,
    master_modules=None,
    reports_modules=None,
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
    if "point_of_sale" in dashboard_modules and not point_of_sale_modules and not is_admin:
        errors.append(
            "Choose at least one Restaurant submodule when Restaurant access is enabled."
        )
    if "point_of_sale_bar" in dashboard_modules and not point_of_sale_bar_modules and not is_admin:
        errors.append(
            "Choose at least one Bar submodule when Bar access is enabled."
        )
    if "hotel_rooms" in dashboard_modules and not hotel_rooms_modules and not is_admin:
        errors.append(
            "Choose at least one Hotel submodule when Hotel access is enabled."
        )
    if "communication_hub" in dashboard_modules and not communication_hub_modules and not is_admin:
        errors.append(
            "Choose at least one Communication Hub submodule when Communication Hub access is enabled."
        )
    if "master" in dashboard_modules and not master_modules and not is_admin:
        errors.append(
            "Choose at least one Master submodule when Master access is enabled."
        )
    if "reports" in dashboard_modules and not reports_modules and not is_admin:
        errors.append(
            "Choose at least one Report submodule when Report access is enabled."
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
    point_of_sale_modules=None,
    point_of_sale_bar_modules=None,
    hotel_rooms_modules=None,
    communication_hub_modules=None,
    master_modules=None,
    reports_modules=None,
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
            point_of_sale_modules,
            point_of_sale_bar_modules,
            hotel_rooms_modules,
            communication_hub_modules,
            master_modules,
            reports_modules,
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
