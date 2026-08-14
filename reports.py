"""Reports dashboard configuration for Hotel Bell Elite."""

from __future__ import annotations

import calendar
from datetime import date, datetime

REPORT_EXPORT_BRAND = "Hotel Bell Elite"
PURCHASE_EXPENSE_LEDGER_NAME = "Purchase & Expense Ledger"
SALARY_PAYMENT_NAME = "Salary Payment"
_REPORT_EXPORT_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def report_export_date_label(value):
    """Filename date fragment: 01 July 26."""
    return f"{value.day:02d} {_REPORT_EXPORT_MONTHS[value.month - 1]} {value.strftime('%y')}"


def report_export_filename(
    report_title,
    filters=None,
    *,
    date_from=None,
    date_to=None,
    date_filter_active=None,
):
    """Hotel Bell Elite {Report Title} 01 July 26 to 31 July 26.xlsx"""
    title = " ".join(str(report_title or "").split())
    payload = filters if isinstance(filters, dict) else {}
    start = date_from if date_from is not None else payload.get("date_from")
    end = date_to if date_to is not None else payload.get("date_to")
    active = date_filter_active
    if active is None:
        if "date_filter_active" in payload:
            active = bool(payload.get("date_filter_active"))
        else:
            active = bool(start and end)
    if active and start and end:
        start_label = report_export_date_label(start)
        end_label = report_export_date_label(end)
        return f"{REPORT_EXPORT_BRAND} {title} {start_label} to {end_label}.xlsx"
    return f"{REPORT_EXPORT_BRAND} {title}.xlsx"


def report_export_month_filename(report_title, year, month):
    """Month-window filename: first day through last day of the payroll month."""
    year = int(year)
    month = int(month)
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])
    return report_export_filename(
        report_title,
        date_from=start,
        date_to=end,
        date_filter_active=True,
    )


def _parse_report_datetime(value):
    """Return ``(datetime, has_time)`` for report display values."""
    if value is None:
        return None, False
    if isinstance(value, datetime):
        return value, True
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day), False
    text = str(value).strip()
    if not text or text in {"—", "-", "never"}:
        return None, False
    text = text.replace("T", " ", 1)
    for fmt, length, has_time in (
        ("%Y-%m-%d %H:%M:%S", 19, True),
        ("%Y-%m-%d %H:%M", 16, True),
        ("%Y-%m-%d", 10, False),
    ):
        chunk = text[:length]
        if len(chunk) < length:
            continue
        try:
            return datetime.strptime(chunk, fmt), has_time
        except ValueError:
            continue
    return None, False


def format_report_date(value, empty="—"):
    """Invoice Ledger date-only display: ``31 July 26``."""
    parsed, _has_time = _parse_report_datetime(value)
    if parsed is None:
        text = "" if value is None else str(value).strip()
        return empty if not text else text
    return (
        f"{parsed.day} {_REPORT_EXPORT_MONTHS[parsed.month - 1]} "
        f"{parsed.strftime('%y')}"
    )


def format_report_time(value, empty=""):
    """Invoice Ledger time: ``15:49`` (empty when the value is date-only)."""
    parsed, has_time = _parse_report_datetime(value)
    if parsed is None or not has_time:
        return empty
    return f"{parsed.hour:02d}:{parsed.minute:02d}"


def format_report_datetime(value, empty="—"):
    """Invoice Ledger display: ``31 July 26`` or ``31 July 26 15:49``."""
    parsed, has_time = _parse_report_datetime(value)
    if parsed is None:
        text = "" if value is None else str(value).strip()
        return empty if not text else text
    label = format_report_date(parsed, empty=empty)
    if has_time:
        return f"{label} {format_report_time(parsed)}"
    return label


REPORT_CATEGORY_LABELS = {
    "all": "All",
    "restaurant": "Restaurant",
    "accounts": "Accounts",
    "hr": "Employee Payroll",
    "sales": "Sales",
    "inventory": "Inventory",
}

# Server-driven report cards. Add entries here to surface new reports on /reports.
# view_route → open/view page; download_route → Excel (or file) export when available.
REPORT_DEFINITIONS = [
    {
        "id": "expense_ledger",
        "name": PURCHASE_EXPENSE_LEDGER_NAME,
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
        "name": "Cash Ledger",
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
        "name": "Credit Payment",
        "description": "Supplier credit payments and ICICI vendor payment export.",
        "icon": "credit",
        "icon_tone": "teal",
        "category": "accounts",
        "view_route": "credit_payment",
        "download_route": "export_credit_payment_report",
        "downloadable": True,
    },
    {
        "id": "tips",
        "name": "Tips",
        "description": "Employee tip collections by outlet — analytics and Excel.",
        "icon": "tip",
        "icon_tone": "rose",
        "category": "hr",
        "view_route": "sales_update_tips_page",
        "download_route": "export_tips_report",
        "downloadable": True,
    },
    {
        "id": "employee_master",
        "name": "Employee Master",
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
        "name": "Monthly Payroll",
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
        "name": "Credit / Advance",
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
        "name": SALARY_PAYMENT_NAME,
        "description": "ICICI fund-transfer bank file for payroll payouts.",
        "icon": "bank",
        "icon_tone": "green",
        "category": "hr",
        "view_route": "bank_report",
        "download_route": "export_bank_report",
        "downloadable": True,
    },
    {
        "id": "menu_margin",
        "name": "Menu & Margin",
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
        "name": "Store",
        "description": "Outlet stock on hand — export Excel from Store.",
        "icon": "package",
        "icon_tone": "amber",
        "category": "inventory",
        "view_route": "stores_stock",
        "download_route": "stores_stock_export",
        "downloadable": True,
    },
    {
        "id": "stock_audit",
        "name": "Stock Audit",
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
        "id": "manager_insight",
        "name": "Manager Insight",
        "description": "Hotel occupancy and room revenue — Duration, current month, and financial year.",
        "icon": "invoice",
        "icon_tone": "teal",
        "category": "sales",
        "view_route": "sales_report_manager_insight",
        "download_route": "sales_report_manager_insight_export",
        "downloadable": True,
    },
    {
        "id": "restaurant_sales",
        "name": "Sales - Restaurant & Bar",
        "description": "Restaurant and Bar POS invoices invoice-wise — filters, KPIs, and Excel export.",
        "icon": "invoice",
        "icon_tone": "violet",
        "category": "sales",
        "view_route": "sales_report_restaurant",
        "download_route": "sales_report_restaurant_export",
        "downloadable": True,
    },
    {
        "id": "menu_sales",
        "name": "Menu Insights",
        "description": "Item-wise menu insights — order count, qty sold, sale value, and Excel export.",
        "icon": "invoice",
        "icon_tone": "amber",
        "category": "sales",
        "view_route": "sales_report_menu",
        "download_route": "sales_report_menu_export",
        "downloadable": True,
    },
    {
        "id": "customer_insights",
        "name": "Customer Insights",
        "description": "Per-customer spend and top ordered item across Hotel, Restaurant, and Bar.",
        "icon": "user",
        "icon_tone": "teal",
        "category": "sales",
        "view_route": "sales_report_customer_insights",
        "download_route": "sales_report_customer_insights_export",
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
