"""Reports dashboard configuration for Hotel Bell Elite."""

from __future__ import annotations

REPORT_CATEGORY_LABELS = {
    "all": "All",
    "restaurant": "Restaurant",
    "accounts": "Accounts",
    "hr": "Employee Payroll",
    "sales": "Sales",
    "inventory": "Inventory",
    "masters": "Masters",
}

# Server-driven report cards. Add entries here to surface new reports on /reports.
# view_route → open/view page; download_route → Excel (or file) export when available.
REPORT_DEFINITIONS = [
    {
        "id": "invoice_ledger",
        "name": "Invoice Ledger Report",
        "description": "Restaurant POS invoices — view ledger and export Excel.",
        "icon": "invoice",
        "icon_tone": "violet",
        "category": "restaurant",
        "view_route": "point_of_sale_invoice_ledger",
        "download_route": "export_pos_invoice_ledger_report",
        "downloadable": True,
    },
    {
        "id": "expense_ledger",
        "name": "Expense Ledger Report",
        "description": "Purchase / expense entries with date filters and Excel export.",
        "icon": "ledger",
        "icon_tone": "blue",
        "category": "accounts",
        "view_route": "purchase_ledger",
        "download_route": "export_purchase_ledger_report",
        "downloadable": True,
    },
    {
        "id": "cash_ledger",
        "name": "Cash Ledger Report",
        "description": "Outlet cash position and movements — view and export.",
        "icon": "cash",
        "icon_tone": "green",
        "category": "accounts",
        "view_route": "cash_ledger",
        "download_route": "export_cash_ledger_report",
        "downloadable": True,
    },
    {
        "id": "credit_payment",
        "name": "Credit Payment Report",
        "description": "Supplier credit payments and ICICI vendor payment export.",
        "icon": "credit",
        "icon_tone": "teal",
        "category": "accounts",
        "view_route": "credit_payment",
        "download_route": "export_credit_payment_report",
        "downloadable": True,
    },
    {
        "id": "purchase_verification",
        "name": "Purchase Verification Report",
        "description": "Verified purchases with Excel download.",
        "icon": "check",
        "icon_tone": "amber",
        "category": "accounts",
        "view_route": "purchase_verification",
        "download_route": "export_purchase_verification_report",
        "downloadable": True,
    },
    {
        "id": "tips",
        "name": "Tips Report",
        "description": "Employee tip collections by outlet — analytics and Excel.",
        "icon": "tip",
        "icon_tone": "rose",
        "category": "hr",
        "view_route": "sales_update_tips_page",
        "download_route": "export_tips_report",
        "downloadable": True,
    },
    {
        "id": "payroll_hub",
        "name": "Payroll Reports",
        "description": "Employee master, wages, attendance, credits, and bank files.",
        "icon": "payroll",
        "icon_tone": "indigo",
        "category": "hr",
        "view_route": "report",
        "download_route": None,
        "downloadable": True,
    },
    {
        "id": "employee_master",
        "name": "Employee Master Report",
        "description": "View employee master records and download Excel.",
        "icon": "person",
        "icon_tone": "cyan",
        "category": "hr",
        "view_route": "employee_master",
        "download_route": "export_employee_master",
        "downloadable": True,
    },
    {
        "id": "monthly_payroll",
        "name": "Monthly Payroll Report",
        "description": "Attendance-based salary ledger — view and export Excel.",
        "icon": "wage",
        "icon_tone": "blue",
        "category": "hr",
        "view_route": "monthly_payroll_report",
        "download_route": "export_employees",
        "downloadable": True,
    },
    {
        "id": "attendance",
        "name": "Attendance Register",
        "description": "Download attendance register for the selected period.",
        "icon": "calendar",
        "icon_tone": "slate",
        "category": "hr",
        "view_route": "attendance_overview",
        "download_route": "export_attendance_register",
        "downloadable": True,
    },
    {
        "id": "credits",
        "name": "Credit / Advance Report",
        "description": "Staff credit and advance export.",
        "icon": "advance",
        "icon_tone": "orange",
        "category": "hr",
        "view_route": "credits_dashboard",
        "download_route": "export_credits_report",
        "downloadable": True,
    },
    {
        "id": "bank",
        "name": "Bank Report",
        "description": "ICICI fund-transfer bank file for payroll payouts.",
        "icon": "bank",
        "icon_tone": "green",
        "category": "hr",
        "view_route": "bank_report",
        "download_route": "export_bank_report",
        "downloadable": True,
    },
    {
        "id": "supplier",
        "name": "Supplier Report",
        "description": "Supplier master Excel export.",
        "icon": "truck",
        "icon_tone": "blue",
        "category": "masters",
        "view_route": "supplier_master",
        "download_route": "export_supplier_report",
        "downloadable": True,
    },
    {
        "id": "customer",
        "name": "Customer Report",
        "description": "Customer master Excel export.",
        "icon": "user",
        "icon_tone": "teal",
        "category": "masters",
        "view_route": "customer_master",
        "download_route": "export_customer_report",
        "downloadable": True,
    },
    {
        "id": "menu_margin",
        "name": "Menu & Margin Report",
        "description": "Menu catalog with food cost and margin — export from Menu Master.",
        "icon": "menu",
        "icon_tone": "violet",
        "category": "restaurant",
        "view_route": "point_of_sale_menu",
        "download_route": None,
        "downloadable": True,
    },
    {
        "id": "stock",
        "name": "Stock Report",
        "description": "Outlet stock on hand — export CSV from Stock.",
        "icon": "package",
        "icon_tone": "amber",
        "category": "inventory",
        "view_route": "stores_stock",
        "download_route": None,
        "downloadable": True,
    },
    {
        "id": "stock_audit",
        "name": "Stock Audit Report",
        "description": "Detailed stock adjustments from weekly audits — view and export Excel.",
        "icon": "package",
        "icon_tone": "teal",
        "category": "inventory",
        "view_route": "stores_stock_audit_report",
        "download_route": "stores_stock_audit_report_export",
        "downloadable": True,
    },
    {
        "id": "hotel_sales",
        "name": "Hotel Sales",
        "description": "Room invoices invoice-wise — filters, KPIs, and Excel export.",
        "icon": "invoice",
        "icon_tone": "blue",
        "category": "sales",
        "view_route": "sales_report_hotel",
        "download_route": "sales_report_hotel_export",
        "downloadable": True,
    },
    {
        "id": "restaurant_sales",
        "name": "Restaurant Sales",
        "description": "Restaurant POS invoices invoice-wise — filters, KPIs, and Excel export.",
        "icon": "invoice",
        "icon_tone": "violet",
        "category": "sales",
        "view_route": "sales_report_restaurant",
        "download_route": "sales_report_restaurant_export",
        "downloadable": True,
    },
    {
        "id": "bar_sales",
        "name": "Bar Sales",
        "description": "Bar POS invoices invoice-wise — filters, KPIs, and Excel export.",
        "icon": "invoice",
        "icon_tone": "rose",
        "category": "sales",
        "view_route": "sales_report_bar",
        "download_route": "sales_report_bar_export",
        "downloadable": True,
    },
]


def _resolve_href(route_name, url_for_fn, fallback="#", **kwargs):
    if not route_name:
        return fallback
    try:
        return url_for_fn(route_name, **kwargs) if kwargs else url_for_fn(route_name)
    except Exception:
        return fallback


def build_reports_dashboard(url_for_fn):
    """Build template payload for the Reports dashboard."""
    reports = []
    for item in REPORT_DEFINITIONS:
        report = dict(item)
        view_kwargs = {}
        if isinstance(item.get("view_kwargs"), dict):
            view_kwargs.update(item["view_kwargs"])
        # Drill-in from Reports hub → destination pages show Back to Reports.
        if item.get("view_route"):
            view_kwargs.setdefault("from_hub", "reports")
        report["view_href"] = _resolve_href(
            item.get("view_route"), url_for_fn, **view_kwargs
        )
        report["download_href"] = _resolve_href(
            item.get("download_route"), url_for_fn, fallback=""
        )
        report["downloadable"] = bool(report["download_href"])
        reports.append(report)

    total_reports = len(reports)
    downloadable = sum(1 for r in reports if r.get("download_href") or r.get("downloadable"))
    categories = {r.get("category") for r in reports if r.get("category")}
    modules = len(categories)

    # Category order follows REPORT_CATEGORY_LABELS (skip "all"); group cards like Tables areas.
    report_sections = []
    for key, label in REPORT_CATEGORY_LABELS.items():
        if key == "all":
            continue
        section_reports = [r for r in reports if r.get("category") == key]
        if not section_reports:
            continue
        report_sections.append(
            {
                "key": key,
                "label": label,
                "reports": section_reports,
                "count": len(section_reports),
            }
        )

    return {
        "reports": reports,
        "report_sections": report_sections,
        "report_categories": [
            {"key": key, "label": label}
            for key, label in REPORT_CATEGORY_LABELS.items()
        ],
        "reports_kpis": {
            "total_reports": total_reports,
            "downloadable": downloadable,
            "modules": modules,
            "categories": len(REPORT_CATEGORY_LABELS) - 1,
        },
    }
