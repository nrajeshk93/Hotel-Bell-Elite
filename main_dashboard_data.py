"""Main Dashboard analytics payload helpers (Neeraj Retail Intelligence layout)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta


_CONTRIBUTION_COLORS = ("#2563EB", "#0EA5E9", "#14B8A6", "#F59E0B", "#8B5CF6")


def inr_compact(value):
    try:
        n = float(value or 0)
    except (TypeError, ValueError):
        n = 0.0
    neg = n < 0
    v = abs(n)
    if v >= 1e7:
        text = f"₹{v / 1e7:.2f} Cr"
    elif v >= 1e5:
        text = f"₹{v / 1e5:.1f} Lakh"
    else:
        text = f"₹{round(v):,}".replace(",", ",")
    return ("−" if neg else "") + text


def pct_change(current, previous):
    try:
        cur = float(current or 0)
        prev = float(previous or 0)
    except (TypeError, ValueError):
        return None
    if prev == 0:
        if cur == 0:
            return 0.0
        return 100.0 if cur > 0 else -100.0
    return round((cur - prev) / abs(prev) * 100, 1)


def day_label(iso_date):
    try:
        return date.fromisoformat(iso_date).strftime("%d %b %Y")
    except (TypeError, ValueError):
        return iso_date or ""


def date_range_days(d0, d1):
    out = []
    cur = d0
    while cur <= d1:
        out.append(cur.isoformat())
        cur += timedelta(days=1)
    return out


def build_sales_trend(daily_series, total_sales):
    span = len(daily_series) or 1
    total = float(total_sales or 0)
    avg_daily = round(total / span, 2)
    positive_days = [x for x in daily_series if x.get("actual_sales", 0) > 0]
    best = max(daily_series, key=lambda x: x.get("actual_sales", 0)) if daily_series else None
    lowest = min(positive_days, key=lambda x: x.get("actual_sales", 0)) if positive_days else None
    return {
        "avg_daily": avg_daily,
        "avg_daily_compact": inr_compact(avg_daily),
        "best_day": {
            "date": best["date"],
            "value": best["actual_sales"],
            "value_compact": inr_compact(best["actual_sales"]),
            "label": day_label(best["date"]),
        }
        if best
        else None,
        "lowest_day": {
            "date": lowest["date"],
            "value": lowest["actual_sales"],
            "value_compact": inr_compact(lowest["actual_sales"]),
            "label": day_label(lowest["date"]),
        }
        if lowest
        else None,
    }


def _week_range_label(week_start, week_end, clip_from, clip_to):
    start = max(week_start, clip_from)
    end = min(week_end, clip_to)
    if start.month == end.month:
        return f'{start.strftime("%b %d")} - {end.strftime("%d")}'
    return f'{start.strftime("%b %d")} - {end.strftime("%b %d")}'


def build_sales_heatmap(daily_series, date_from, date_to):
    day_map = {item["date"]: item for item in daily_series}
    max_sales = max((item.get("actual_sales") or 0 for item in daily_series), default=0.0)

    growth_map = {}
    prev_sales = None
    for item in daily_series:
        sales = item.get("actual_sales") or 0
        if prev_sales is not None:
            growth_map[item["date"]] = pct_change(sales, prev_sales)
        else:
            growth_map[item["date"]] = None
        prev_sales = sales

    week_start = date_from - timedelta(days=date_from.weekday())
    columns = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weeks = []
    cur = week_start
    while cur <= date_to:
        week_end = cur + timedelta(days=6)
        cells = []
        for offset in range(7):
            cell_date = cur + timedelta(days=offset)
            iso = cell_date.isoformat()
            in_range = date_from <= cell_date <= date_to
            if not in_range:
                cells.append(
                    {
                        "date": iso,
                        "in_range": False,
                        "sales": 0.0,
                        "transactions": 0,
                        "growth_pct": None,
                        "intensity": 0.0,
                        "has_sales": False,
                    }
                )
                continue
            item = day_map.get(iso, {})
            sales = float(item.get("actual_sales") or 0)
            txn = int(item.get("transaction_count") or 0)
            intensity = round(sales / max_sales, 4) if max_sales > 0 else 0.0
            cells.append(
                {
                    "date": iso,
                    "in_range": True,
                    "sales": round(sales, 2),
                    "transactions": txn,
                    "growth_pct": growth_map.get(iso),
                    "intensity": intensity,
                    "has_sales": sales > 0,
                }
            )

        label_start = max(cur, date_from)
        label_end = min(week_end, date_to)
        weeks.append(
            {
                "label": _week_range_label(cur, week_end, date_from, date_to),
                "week_start": cur.isoformat(),
                "week_end": week_end.isoformat(),
                "filter_from": label_start.isoformat(),
                "filter_to": label_end.isoformat(),
                "cells": cells,
            }
        )
        cur += timedelta(days=7)

    return {
        "weeks": weeks,
        "columns": columns,
        "max_sales": round(max_sales, 2),
    }


def payment_mode_pct(digital, cash):
    dig = float(digital or 0)
    cash_v = float(cash or 0)
    total = dig + cash_v
    if total <= 0:
        return 0.0, 0.0
    dig_pct = round(dig / total * 100, 1)
    return dig_pct, round(100.0 - dig_pct, 1)


def sparkline_series_from_values(dates, values):
    series = []
    prev = None
    for iso, value in zip(dates, values):
        val = float(value or 0)
        series.append(
            {
                "date": iso,
                "value": val,
                "change_pct": pct_change(val, prev) if prev is not None else None,
            }
        )
        prev = val
    return series


def build_outlet_boards(outlet_totals, prev_outlet_totals, grand_sales):
    """Leaderboard + donut contribution for Hotel / Restaurant / Bar."""
    rows = []
    for name, sales in sorted(outlet_totals.items(), key=lambda x: -x[1]):
        sales = round(float(sales or 0), 2)
        if sales <= 0:
            continue
        share = (sales / grand_sales * 100) if grand_sales > 0 else 0.0
        growth = pct_change(sales, prev_outlet_totals.get(name, 0.0))
        rows.append(
            {
                "label": name,
                "name": name,
                "sales": sales,
                "sales_compact": inr_compact(sales),
                "share_pct": round(share, 1),
                "growth_pct": growth,
            }
        )
    for i, item in enumerate(rows, start=1):
        item["rank"] = i

    contribution_items = []
    for i, row in enumerate(rows):
        contribution_items.append(
            {
                "name": row["name"],
                "sales": row["sales"],
                "sales_compact": row["sales_compact"],
                "share_pct": row["share_pct"],
                "growth_pct": row["growth_pct"],
                "color": _CONTRIBUTION_COLORS[i % len(_CONTRIBUTION_COLORS)],
            }
        )
    contribution = {
        "total_sales": round(float(grand_sales or 0), 2),
        "total_sales_compact": inr_compact(grand_sales),
        "entries": contribution_items,
        "top_contributor": {
            "name": contribution_items[0]["name"],
            "share_pct": contribution_items[0]["share_pct"],
        }
        if contribution_items
        else None,
    }
    return rows, contribution


def build_dow_avg(daily_series):
    dow_names = [
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
    ]
    dow_totals = defaultdict(lambda: {"sum": 0.0, "count": 0})
    for item in daily_series:
        sales = float(item.get("actual_sales") or 0)
        if sales <= 0:
            continue
        try:
            wd = date.fromisoformat(item["date"]).weekday()
        except (TypeError, ValueError):
            continue
        dow_totals[wd]["sum"] += sales
        dow_totals[wd]["count"] += 1
    out = []
    for i, name in enumerate(dow_names):
        bucket = dow_totals[i]
        avg = bucket["sum"] / bucket["count"] if bucket["count"] else 0.0
        out.append({"day": name, "avg_sales": round(avg, 2)})
    return out


def _format_qty_label(qty):
    try:
        n = float(qty or 0)
    except (TypeError, ValueError):
        n = 0.0
    if abs(n - round(n)) < 1e-9:
        return str(int(round(n)))
    return f"{n:.2f}".rstrip("0").rstrip(".")


def build_top_selling_items(rows, limit=5, sort_by="qty"):
    """Top menu items by quantity or revenue; returns count + sale value."""
    try:
        limit_n = max(0, int(limit))
    except (TypeError, ValueError):
        limit_n = 5
    sort_key = str(sort_by or "qty").strip().lower()
    if sort_key in ("revenue", "sale", "sales", "sale_value", "value"):
        sort_key = "revenue"
    else:
        sort_key = "qty"

    buckets = {}
    for row in rows or []:
        try:
            menu_id = int(row.get("menu_item_id") or 0)
        except (TypeError, ValueError):
            menu_id = 0
        name = str(row.get("item_name") or "Item").strip() or "Item"
        key = ("id", menu_id) if menu_id > 0 else ("name", name.casefold())
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {"name": name, "qty": 0.0, "sale_value": 0.0}
            buckets[key] = bucket
        elif menu_id > 0 and not bucket["name"]:
            bucket["name"] = name
        try:
            qty = float(row.get("qty_sold") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        try:
            sale = float(row.get("sale_value") or 0)
        except (TypeError, ValueError):
            sale = 0.0
        bucket["qty"] += qty
        bucket["sale_value"] += sale

    ranked = []
    for bucket in buckets.values():
        qty = float(bucket["qty"] or 0)
        if qty <= 0:
            continue
        sale_value = round(float(bucket["sale_value"] or 0), 2)
        unit_price = round(sale_value / qty, 2) if qty else 0.0
        qty_rounded = round(qty, 2) if abs(qty - round(qty)) >= 1e-9 else int(round(qty))
        qty_label = _format_qty_label(qty)
        ranked.append(
            {
                "name": bucket["name"],
                "qty": qty_rounded,
                "qty_label": qty_label,
                "qty_display": f"{qty_label} sold",
                "unit_price": unit_price,
                "unit_price_compact": inr_compact(unit_price),
                "sale_value": sale_value,
                "sale_value_compact": inr_compact(sale_value),
            }
        )

    if sort_key == "revenue":
        ranked.sort(
            key=lambda item: (
                -float(item["sale_value"]),
                -float(item["qty"]),
                item["name"].casefold(),
            )
        )
    else:
        ranked.sort(
            key=lambda item: (
                -float(item["qty"]),
                -float(item["sale_value"]),
                item["name"].casefold(),
            )
        )
    out = ranked[:limit_n]
    for i, item in enumerate(out, start=1):
        item["rank"] = i
    return out
