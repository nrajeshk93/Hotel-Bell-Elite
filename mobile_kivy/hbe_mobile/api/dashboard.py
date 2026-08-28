"""Main dashboard — parse SSR JSON embed (and optional WebView URL)."""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlencode

from hbe_mobile.api.client import ApiClient, extract_script_json
from hbe_mobile.models import DashboardSnapshot

# Web /main-dashboard period pills. Mobile landing uses "today" (ops pulse for
# this shift); the web form defaults to 30d (manager review window).
# NEVER send legacy "week" / "month" — they are not valid web period keys.
VALID_PERIODS = ("today", "yesterday", "7d", "30d", "mtd", "qtd", "ytd")

# Executive five, display order: Sales → Digital → Cash → Expense → Difference.
_EXECUTIVE_KPIS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("actual_sales", "Sales", ("actual_sales", "sales", "total_sales")),
    ("digital_transactions", "Digital", ("digital_transactions", "digital", "digital_collection")),
    ("cash", "Cash", ("cash", "cash_collection")),
    ("expense", "Expense", ("expense", "expenses")),
    ("difference", "Difference", ("difference",)),
)

_LOCATION_ALL = "All"


def normalize_period(period: str | None) -> str:
    key = (period or "").strip().lower()
    if key not in VALID_PERIODS:
        raise ValueError(
            f"Unsupported dashboard period {period!r}. "
            f"Use one of: {', '.join(VALID_PERIODS)}."
        )
    return key


def dashboard_query_params(*, period: str, location: str | None = None) -> dict[str, str]:
    """Query for GET /main-dashboard. Omit location when unset or All (web default)."""
    params = {"period": normalize_period(period)}
    loc = (location or "").strip()
    if loc and loc.casefold() != _LOCATION_ALL.casefold():
        params["location"] = loc
    return params


def format_inr(value: Any, *, decimals: int = 0) -> str:
    """Indian grouping with rupee sign (KPI cards use whole rupees by default)."""
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    neg = n < 0
    n = abs(n)
    if decimals <= 0:
        int_part = str(int(round(n)))
        frac = ""
    else:
        whole, frac_digits = f"{n:.{int(decimals)}f}".split(".")
        int_part = whole
        frac = "." + frac_digits
    grouped = _indian_group(int_part)
    return ("−" if neg else "") + "₹" + grouped + frac


def _indian_group(digits: str) -> str:
    if len(digits) <= 3:
        return digits
    last3 = digits[-3:]
    rest = digits[:-3]
    parts: list[str] = []
    while len(rest) > 2:
        parts.append(rest[-2:])
        rest = rest[:-2]
    if rest:
        parts.append(rest)
    return ",".join(reversed(parts)) + "," + last3


def _to_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _unwrap_dashboard(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    inner = raw.get("dashboard")
    if isinstance(inner, dict) and (
        "kpis" in inner or "sales_trend" in inner or "payment_mode" in inner
    ):
        return inner
    return raw


def _index_structured_kpis(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    indexed: dict[str, dict[str, Any]] = {}
    value = raw.get("kpis")
    if isinstance(value, list):
        for item in value:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or item.get("id") or item.get("metric") or "").strip()
            if key:
                indexed[key] = item
    elif isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, dict):
                indexed[str(key)] = item
            else:
                indexed[str(key)] = {"key": key, "value": item}
    return indexed


def _kpi_value(item: dict[str, Any] | None, fallback: Any = None) -> Optional[float]:
    if isinstance(item, dict):
        for field in ("value", "amount", "total", "sales"):
            parsed = _to_float(item.get(field))
            if parsed is not None:
                return parsed
    return _to_float(fallback)


def _executive_kpis(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Prefer structured kpis list; map to ordered executive five."""
    indexed = _index_structured_kpis(raw)
    kpis: list[dict[str, Any]] = []
    for canonical, label, aliases in _EXECUTIVE_KPIS:
        item: dict[str, Any] | None = None
        for alias in aliases:
            if alias in indexed:
                item = indexed[alias]
                break
            if alias in raw and not isinstance(raw.get(alias), (list, dict)):
                item = {"key": canonical, "value": raw.get(alias)}
                break
        value = _kpi_value(item, raw.get(canonical))
        if value is None:
            value = 0.0
        row: dict[str, Any] = {
            "key": canonical,
            "label": label,
            "value": value,
        }
        compact = ""
        if isinstance(item, dict):
            compact = str(item.get("value_compact") or "")
            change = item.get("change_pct")
            if change is None:
                change = item.get("trend")
            change_f = _to_float(change)
            if change_f is not None:
                row["change_pct"] = change_f
            prior = None
            for field in ("prior", "previous", "prior_value", "previous_value"):
                prior = _to_float(item.get(field))
                if prior is not None:
                    break
            if prior is not None:
                row["prior"] = prior
        row["value_display"] = compact or format_inr(value)
        kpis.append(row)
    return kpis


def _trend_day(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    amount = _to_float(payload.get("value", payload.get("amount")))
    if amount is None and not (payload.get("label") or payload.get("date")):
        return None
    out: dict[str, Any] = {
        "date": str(payload.get("date") or ""),
        "label": str(payload.get("label") or payload.get("date") or ""),
        "amount": amount if amount is not None else 0.0,
    }
    compact = str(payload.get("value_compact") or payload.get("amount_display") or "")
    out["amount_display"] = compact or format_inr(out["amount"])
    return out


def _sales_trend_summary(raw: dict[str, Any]) -> dict[str, Any]:
    trend = raw.get("sales_trend")
    if not isinstance(trend, dict) or not trend:
        return {}
    summary: dict[str, Any] = {}
    avg = _to_float(trend.get("avg_daily", trend.get("avg")))
    if avg is not None:
        summary["avg"] = avg
        compact = str(trend.get("avg_daily_compact") or "")
        summary["avg_display"] = compact or format_inr(avg, decimals=2)
    best = _trend_day(trend.get("best_day") or trend.get("best"))
    if best:
        summary["best"] = best
    lowest = _trend_day(trend.get("lowest_day") or trend.get("lowest"))
    if lowest:
        summary["lowest"] = lowest
    return summary


def _company_leaderboard(raw: dict[str, Any]) -> list[dict[str, Any]]:
    rows = raw.get("company_leaderboard")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("label") or "").strip()
        amount = _to_float(item.get("sales", item.get("amount", item.get("value"))))
        if not name and amount is None:
            continue
        entry: dict[str, Any] = {
            "name": name,
            "amount": amount if amount is not None else 0.0,
        }
        compact = str(item.get("sales_compact") or item.get("amount_display") or "")
        entry["amount_display"] = compact or format_inr(entry["amount"])
        share = _to_float(item.get("share_pct"))
        if share is not None:
            entry["share_pct"] = share
        out.append(entry)
    return out


def _payment_mix(raw: dict[str, Any], kpis: list[dict[str, Any]]) -> dict[str, Any]:
    mode = raw.get("payment_mode") if isinstance(raw.get("payment_mode"), dict) else {}
    stack = raw.get("digital_cash_stack") if isinstance(raw.get("digital_cash_stack"), list) else []

    kpi_by_key = {str(row.get("key")): row for row in kpis}
    digital_amount = _to_float((kpi_by_key.get("digital_transactions") or {}).get("value"))
    cash_amount = _to_float((kpi_by_key.get("cash") or {}).get("value"))
    if digital_amount is None:
        digital_amount = _to_float(mode.get("digital") or mode.get("digital_amount"))
    if cash_amount is None:
        cash_amount = _to_float(mode.get("cash") or mode.get("cash_amount"))

    digital_pct = _to_float(mode.get("digital_pct"))
    cash_pct = _to_float(mode.get("cash_pct"))
    if digital_pct is None or cash_pct is None:
        last = next((item for item in reversed(stack) if isinstance(item, dict)), None)
        if last:
            if digital_pct is None:
                digital_pct = _to_float(last.get("digital_pct"))
            if cash_pct is None:
                cash_pct = _to_float(last.get("cash_pct"))
    if digital_pct is None or cash_pct is None:
        dig = float(digital_amount or 0)
        cash_v = float(cash_amount or 0)
        total = dig + cash_v
        if total > 0:
            digital_pct = round(dig / total * 100, 1)
            cash_pct = round(100.0 - digital_pct, 1)

    if digital_pct is None and cash_pct is None and digital_amount is None and cash_amount is None:
        return {}

    mix: dict[str, Any] = {
        "digital_pct": digital_pct if digital_pct is not None else 0.0,
        "cash_pct": cash_pct if cash_pct is not None else 0.0,
    }
    if digital_amount is not None:
        mix["digital_amount"] = digital_amount
    if cash_amount is not None:
        mix["cash_amount"] = cash_amount
    digital_trend = _to_float(mode.get("digital_trend"))
    cash_trend = _to_float(mode.get("cash_trend"))
    if digital_trend is not None:
        mix["digital_trend"] = digital_trend
    if cash_trend is not None:
        mix["cash_trend"] = cash_trend
    return mix


def _item_rows(raw: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = raw.get(key)
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict)]


def snapshot_from_dashboard_data(
    raw: Any,
    *,
    period: str = "today",
    location: str | None = None,
) -> DashboardSnapshot:
    """Build a snapshot from a parsed #md-dashboard-data object."""
    period_n = normalize_period(period)
    loc = (location or "").strip() or _LOCATION_ALL
    data = _unwrap_dashboard(raw)
    kpis = _executive_kpis(data)
    return DashboardSnapshot(
        period=str(data.get("period") or period_n),
        location=str(data.get("location") or loc),
        kpis=kpis,
        raw=data,
        sales_trend=_sales_trend_summary(data),
        company_leaderboard=_company_leaderboard(data),
        payment_mix=_payment_mix(data, kpis),
        top_selling_items=_item_rows(data, "top_selling_items"),
        top_selling_items_by_revenue=_item_rows(data, "top_selling_items_by_revenue"),
    )


def fetch_dashboard(
    client: ApiClient,
    *,
    period: str = "today",
    location: str | None = None,
) -> DashboardSnapshot:
    params = dashboard_query_params(period=period, location=location)
    html = client.get_text("/main-dashboard", params=params)
    raw = extract_script_json(html, "md-dashboard-data")
    return snapshot_from_dashboard_data(raw, period=params["period"], location=location)


def dashboard_webview_url(
    client: ApiClient,
    *,
    period: str = "today",
    location: str | None = None,
) -> str:
    params = dashboard_query_params(period=period, location=location)
    return client.absolute_url(f"/main-dashboard?{urlencode(params)}")
