"""Navigation destinations mirroring de-sidebar Phase 1 (+ Indent Approval).

`access_key` maps to flags from workspace_access.mobile_module_access /
GET /api/mobile/session.
"""

from __future__ import annotations

NAV_ITEMS = [
    {"id": "home", "label": "Home", "screen": "home", "group": None, "access_key": "home"},
    {
        "id": "main_dashboard",
        "label": "Dashboard",
        "screen": "dashboard",
        "group": None,
        "access_key": "main_dashboard",
    },
    {
        "id": "indent_request",
        "label": "Indent Request",
        "screen": "indent_request",
        "group": "Purchase & Inventory",
        "access_key": "indent_request",
    },
    {
        "id": "indent_approvals",
        "label": "Indent Approval",
        "screen": "indent_approvals",
        "group": "Purchase & Inventory",
        "access_key": "indent_approvals",
    },
    {
        "id": "pos_invoice",
        "label": "POS",
        "screen": "pos_invoice",
        "group": "Restaurant",
        "access_key": "pos",
    },
    {
        "id": "kot",
        "label": "KOT",
        "screen": "kot",
        "group": "Restaurant",
        "access_key": "kot",
    },
    {
        "id": "pos_bar_invoice",
        "label": "POS",
        "screen": "pos_bar_invoice",
        "group": "Bar",
        "access_key": "pos_bar",
    },
    {
        "id": "kot_bar",
        "label": "KOT",
        "screen": "kot_bar",
        "group": "Bar",
        "access_key": "kot_bar",
    },
    {
        "id": "payroll_employee",
        "label": "Employee",
        "screen": "payroll_employees",
        "group": "Employee Payroll",
        "access_key": "payroll_employee",
    },
    {
        "id": "payroll_attendance",
        "label": "Attendance",
        "screen": "payroll_attendance",
        "group": "Employee Payroll",
        "access_key": "payroll_attendance",
    },
    {
        "id": "payroll_credit",
        "label": "Credit",
        "screen": "payroll_credit",
        "group": "Employee Payroll",
        "access_key": "payroll_credit",
    },
    {
        "id": "payroll_tips",
        "label": "Tips",
        "screen": "payroll_tips",
        "group": "Employee Payroll",
        "access_key": "payroll_tips",
    },
    {
        "id": "approvals",
        "label": "Approvals",
        "screen": "approvals",
        "group": "Accounts",
        "access_key": "approvals",
    },
]


def can_access(access: dict | None, key: str) -> bool:
    if not key or key == "home":
        return True
    if not access:
        return False
    if access.get("is_admin"):
        return True
    return bool(access.get(key))


def filter_nav_items(access: dict | None) -> list[dict]:
    return [item for item in NAV_ITEMS if can_access(access, str(item.get("access_key") or ""))]
