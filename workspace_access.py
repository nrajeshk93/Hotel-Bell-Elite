"""Workspace module registry and permission helpers for Hotel Bell Elite."""

from werkzeug.security import generate_password_hash

_SALES_ANALYTICS_SUBMODULES = (
    {"key": "dashboard", "label": "Dashboard"},
    {"key": "hotel", "label": "Sales Update - Hotel"},
    {"key": "bar", "label": "Sales Update - Bar"},
    {"key": "restaurant", "label": "Sales Update - Restaurant"},
    {"key": "room_transfer", "label": "Room Transfer"},
)

_USER_ACCESS_SUBMODULES = (
    {"key": "users", "label": "Users"},
    {"key": "add", "label": "Add User"},
)

_PAYROLL_SUBMODULES = (
    {"key": "employee", "label": "Employee"},
    {"key": "report", "label": "Report"},
    {"key": "attendance", "label": "Attendance"},
    {"key": "credit", "label": "Credit"},
)

_ACCOUNTS_SUBMODULES = (
    {"key": "purchase_ledger", "label": "Purchase Ledger"},
    {"key": "cash_ledger", "label": "Cash Ledger"},
    {"key": "credit_payment", "label": "Credit Payment"},
    {"key": "purchase_verification", "label": "Purchase Verification"},
    {"key": "supplier_master", "label": "Supplier Master"},
)

# Single registry aligned with the workspace sidebar and access-management UI.
# Add a new top-level module here and wire its endpoints to auto-include it everywhere.
_WORKSPACE_MODULE_REGISTRY = (
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

_ACCESS_MODULE_UI_META = {
    "sales_analytics": {
        "icon": "trending-up",
        "description": "Daily sales updates, room transfers, and analytics dashboards.",
    },
    "access_management": {
        "icon": "shield-check",
        "description": "Manage workspace users and assign module access.",
    },
    "accounts": {
        "icon": "wallet",
        "description": "Ledger, payments, and financial records.",
    },
    "employee_payroll": {
        "icon": "users",
        "description": "Manage employees, payroll reports, attendance, and credits.",
    },
}

_PUBLIC_ENDPOINTS = {"index", "login", "logout", "static", "home"}

_OUTLET_WRITE_ENDPOINTS = {
    "save_sales_update",
    "upload_report",
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

_SALES_ANALYTICS_ENDPOINT_GROUPS = {
    "dashboard": {"dashboard"},
    "hotel": {
        "sales_update_hotel",
        "upload_hotel_occupancy_report",
        "save_hotel_ledger",
        "clear_hotel_ledger",
        "create_supplier",
    },
    "bar": {
        "sales_update_bar",
        "sales_update",
        "sales_update_entry",
        *_OUTLET_WRITE_ENDPOINTS,
    },
    "restaurant": {
        "sales_update_restaurant",
        *_OUTLET_WRITE_ENDPOINTS,
    },
    "room_transfer": {
        "sales_update_room_transfer",
        "save_room_transfer_status",
        "create_room_transfer_payment",
        "reverse_room_transfer_payment",
    },
}

_SALES_ANALYTICS_PARENT_ENDPOINTS = set().union(*_SALES_ANALYTICS_ENDPOINT_GROUPS.values())

_ACCESS_ENDPOINT_GROUPS = {
    "users": {"delete_access_user"},
    "add": set(),
}
_ACCESS_MANAGEMENT_ENDPOINTS = {"access_management", "save_access_user"}
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
        "add_employee",
        "edit_employee",
        "delete_employee",
        "download_employee_template",
        "upload_employees",
        "export_employees",
        "export_employee_master",
    },
    "report": {"report", "export_wage_register", "export_bank_report"},
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
}
_PAYROLL_PARENT_ENDPOINTS = set().union(*_PAYROLL_ENDPOINT_GROUPS.values())


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
            for child in child_cfg["submodules"]:
                node["permission_children"].append({
                    "key": child["key"],
                    "label": child["label"],
                    "scope": child_cfg["scope"],
                    "field_name": child_cfg["field_name"],
                    "parent_key": module["key"],
                })
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
        child_cfg = _ACCESS_MODULE_CHILDREN.get(module["key"])
        if child_cfg:
            for child in child_cfg["submodules"]:
                node["children"].append({
                    "id": f"{module['key']}.{child['key']}",
                    "label": child["label"],
                    "icon": "dot",
                    "description": "",
                    "dashboardKey": module["key"],
                    "fieldName": child_cfg["field_name"],
                    "fieldValue": child["key"],
                    "children": [],
                })
        tree.append(node)
    return tree


def load_user_permissions(conn, user_id):
    rows = conn.execute(
        "SELECT scope, item_key FROM user_permissions WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    dashboard_access = set()
    sales_analytics_access = set()
    user_access = set()
    payroll_access = set()
    accounts_access = set()
    for row in rows:
        scope = (row["scope"] or "").strip()
        item_key = (row["item_key"] or "").strip()
        if scope == "dashboard" and item_key:
            dashboard_access.add(item_key)
        elif scope == "sales_analytics" and item_key:
            sales_analytics_access.add(item_key)
        elif scope == "user_access" and item_key:
            user_access.add(item_key)
        elif scope == "payroll" and item_key:
            payroll_access.add(item_key)
        elif scope == "accounts" and item_key:
            accounts_access.add(item_key)
        elif scope == "dashboard" and item_key == "sales_update":
            # Legacy key from earlier builds.
            dashboard_access.add("sales_analytics")
    return dashboard_access, sales_analytics_access, user_access, payroll_access, accounts_access


def build_user_context(conn, row):
    if not row:
        return None
    user = dict(row)
    user["is_admin"] = bool(user.get("is_admin"))
    user["is_active"] = bool(user.get("is_active"))
    (
        dashboard_access,
        sales_analytics_access,
        user_access,
        payroll_access,
        accounts_access,
    ) = load_user_permissions(conn, user["id"])
    user["dashboard_access"] = dashboard_access
    user["sales_analytics_access"] = sales_analytics_access
    user["user_access"] = user_access
    user["payroll_access"] = payroll_access
    user["accounts_access"] = accounts_access
    user["display_name"] = (user.get("full_name") or user.get("username") or "User").strip()
    return user


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
    return submodule_key in user.get("payroll_access", set())


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


def user_can_access_supplier_master(user):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    if user_can_access_accounts_submodule(user, "supplier_master"):
        return True
    return "suppliers" in user.get("sales_analytics_access", set())


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
    return [item["key"] for item in _DASHBOARD_MODULES if item["key"] in dashboard_access]


def payroll_access_list(user):
    if not user:
        return []
    if user.get("is_admin"):
        return [item["key"] for item in _PAYROLL_SUBMODULES]
    return [
        item["key"]
        for item in _PAYROLL_SUBMODULES
        if item["key"] in user.get("payroll_access", set())
    ]


def accounts_access_list(user):
    if not user:
        return []
    unlocked = _accounts_access_keys(user)
    return [item["key"] for item in _ACCOUNTS_SUBMODULES if item["key"] in unlocked]


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
    if endpoint in _SALES_ANALYTICS_PARENT_ENDPOINTS:
        return "sales_analytics"
    if endpoint in _ACCESS_MANAGEMENT_ENDPOINTS:
        return "access_management"
    if endpoint in _ACCOUNTS_ENDPOINTS:
        return "accounts"
    if endpoint in _PAYROLL_PARENT_ENDPOINTS:
        return "employee_payroll"
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
    return username == "admin"


def set_user_permissions(
    conn,
    user_id,
    dashboard_modules,
    sales_analytics_modules=None,
    user_access_modules=None,
    payroll_modules=None,
    accounts_modules=None,
):
    dashboard_modules = sorted({
        module for module in dashboard_modules if module in _DASHBOARD_MODULE_LABELS
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

    if sales_analytics_modules and "sales_analytics" not in dashboard_modules:
        dashboard_modules.append("sales_analytics")
        dashboard_modules = sorted(set(dashboard_modules))
    if user_access_modules and "access_management" not in dashboard_modules:
        dashboard_modules.append("access_management")
        dashboard_modules = sorted(set(dashboard_modules))
    if payroll_modules and "employee_payroll" not in dashboard_modules:
        dashboard_modules.append("employee_payroll")
        dashboard_modules = sorted(set(dashboard_modules))
    if accounts_modules and "accounts" not in dashboard_modules:
        dashboard_modules.append("accounts")
        dashboard_modules = sorted(set(dashboard_modules))

    conn.execute("DELETE FROM user_permissions WHERE user_id = ?", (user_id,))
    for module_key in dashboard_modules:
        conn.execute(
            "INSERT INTO user_permissions (user_id, scope, item_key) VALUES (?, ?, ?)",
            (user_id, "dashboard", module_key),
        )
    if "sales_analytics" in dashboard_modules:
        for module_key in sales_analytics_modules:
            conn.execute(
                "INSERT INTO user_permissions (user_id, scope, item_key) VALUES (?, ?, ?)",
                (user_id, "sales_analytics", module_key),
            )
    if "access_management" in dashboard_modules:
        for module_key in user_access_modules:
            conn.execute(
                "INSERT INTO user_permissions (user_id, scope, item_key) VALUES (?, ?, ?)",
                (user_id, "user_access", module_key),
            )
    if "employee_payroll" in dashboard_modules:
        for module_key in payroll_modules:
            conn.execute(
                "INSERT INTO user_permissions (user_id, scope, item_key) VALUES (?, ?, ?)",
                (user_id, "payroll", module_key),
            )
    if "accounts" in dashboard_modules:
        for module_key in accounts_modules:
            conn.execute(
                "INSERT INTO user_permissions (user_id, scope, item_key) VALUES (?, ?, ?)",
                (user_id, "accounts", module_key),
            )


def fetch_access_management_users(conn, selected_user_id=None):
    user_rows = conn.execute(
        "SELECT * FROM users ORDER BY is_admin DESC, LOWER(username), id"
    ).fetchall()
    users = []
    for row in user_rows:
        user = build_user_context(conn, row)
        user["dashboard_labels"] = [
            _DASHBOARD_MODULE_LABELS[key] for key in dashboard_access_list(user)
        ]
        user["sales_analytics_labels"] = [
            _SALES_ANALYTICS_SUBMODULE_LABELS[key]
            for key in sales_analytics_access_list(user)
        ]
        user["user_access_labels"] = [
            _USER_ACCESS_SUBMODULE_LABELS[key] for key in user_access_submodule_list(user)
        ]
        user["payroll_labels"] = [
            _PAYROLL_SUBMODULE_LABELS[key] for key in payroll_access_list(user)
        ]
        user["accounts_labels"] = [
            _ACCOUNTS_SUBMODULE_LABELS[key] for key in accounts_access_list(user)
        ]
        users.append(user)

    selected_user = None
    if selected_user_id:
        for user in users:
            if int(user["id"]) == int(selected_user_id):
                selected_user = user
                break
    return users, selected_user


def validate_access_user_form(
    conn,
    *,
    actor,
    user_id,
    username,
    password,
    is_admin,
    dashboard_modules,
    sales_analytics_modules,
    user_access_modules,
    payroll_modules=None,
    accounts_modules=None,
):
    errors = []
    actor_is_admin = bool(actor and actor.get("is_admin"))

    if not username:
        errors.append("Username is required.")
    if not user_id and not password:
        errors.append("Password is required for a new user.")
    if not is_admin and not dashboard_modules:
        errors.append("Select at least one dashboard module for a non-admin user.")
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
            errors.append("Only administrators can grant administrator access.")
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

    return errors, original


def save_access_user_record(
    conn,
    *,
    user_id,
    username,
    full_name,
    password,
    is_admin,
    dashboard_modules,
    sales_analytics_modules,
    user_access_modules,
    payroll_modules=None,
    accounts_modules=None,
    sql_now,
):
    if user_id:
        params = [username, full_name, int(is_admin)]
        update_sql = (
            f"UPDATE users SET username = ?, full_name = ?, is_admin = ?, "
            f"is_active = 1, updated_at = {sql_now}"
        )
        if password:
            update_sql += ", password_hash = ?"
            params.append(generate_password_hash(password))
        update_sql += " WHERE id = ?"
        params.append(user_id)
        conn.execute(update_sql, tuple(params))
        saved_user_id = user_id
        result_flag = "updated"
    else:
        conn.execute(
            f"""INSERT INTO users
                (username, full_name, password_hash, is_admin, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, 1, {sql_now}, {sql_now})""",
            (username, full_name, generate_password_hash(password), int(is_admin)),
        )
        saved_user_id = conn.execute(
            "SELECT id FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()["id"]
        result_flag = "created"

    set_user_permissions(
        conn,
        saved_user_id,
        dashboard_modules,
        sales_analytics_modules,
        user_access_modules,
        payroll_modules,
        accounts_modules,
    )
    return saved_user_id, result_flag
