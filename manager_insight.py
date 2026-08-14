"""Hotel Manager Insight — occupancy and room revenue by Duration / MTD / YTD."""

from __future__ import annotations

import calendar
import json
from datetime import date, timedelta

from db import (
    _hotel_parse_iso_date,
    _hotel_room_has_inhouse_stay,
    _normalize_hotel_room_status,
    backfill_hotel_room_invoices_from_layout,
    ensure_hotel_room_invoices_schema,
    get_hotel_rooms_layout,
    indian_fiscal_year_bounds,
)

RATE_PLANS = ("EP", "CP", "MAP", "AP")
OCC_KEYS = ("single", "double", "triple", "quad")
PAY_KEYS = ("bank", "cash", "credit", "card", "upi")

ROW_SPECS = (
    ("total_rooms", "Total Rooms", "count"),
    ("rooms_sold", "Rooms Sold", "count"),
    ("pax", "Pax", "count"),
    ("extra_person", "Extraperson", "count"),
    ("single", "Single Occupied", "count"),
    ("double", "Double Occupied", "count"),
    ("triple", "Triple Occupied", "count"),
    ("quad", "Quadruple Occupied", "count"),
    ("pct_occupancy", "% of Occupancy", "pct"),
    ("pct_single", "% of Single Occupancy", "pct"),
    ("pct_double", "% of Double Occupancy", "pct"),
    ("pct_triple", "% of Triple Occupancy", "pct"),
    ("pct_quad", "% of Quadruple Occupancy", "pct"),
    ("ep_room", "EP Room", "count"),
    ("cp_room", "CP Room", "count"),
    ("map_room", "MAP Room", "count"),
    ("ap_room", "AP Room", "count"),
    ("ep_pax", "EP Pax", "count"),
    ("cp_pax", "CP Pax", "count"),
    ("map_pax", "MAP Pax", "count"),
    ("ap_pax", "AP Pax", "count"),
    ("revenue", "Total Room Revenue", "money"),
    ("arr", "ARR", "money"),
    ("arp", "ARP", "money"),
    ("bank", "Bank Transfer", "money"),
    ("cash", "Cash", "money"),
    ("credit", "Credit", "money"),
    ("card", "Card", "money"),
    ("upi", "UPI", "money"),
)


def period_nights(start, end):
    if not start or not end or end < start:
        return 0
    return (end - start).days + 1


_MONTH_NAMES = (
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


def selected_month_window(anchor, today):
    """Full calendar month of `anchor`; current month is 1st through today."""
    ref = today or date.today()
    start = date(anchor.year, anchor.month, 1)
    last_day = calendar.monthrange(anchor.year, anchor.month)[1]
    end = date(anchor.year, anchor.month, last_day)
    if (start.year, start.month) == (ref.year, ref.month):
        end = min(end, ref)
    return start, end


def month_column_label(anchor):
    if not anchor:
        return "MTD"
    return f"{_MONTH_NAMES[anchor.month - 1]} Month"


def manager_insight_windows(today, date_from, date_to):
    """Duration is the picker; MTD is that range's calendar month; YTD is current FY."""
    ref = today or date.today()
    anchor = date_from or date_to or ref
    mtd_start, mtd_end = selected_month_window(anchor, ref)
    fy_start, _fy_ref = indian_fiscal_year_bounds(ref)
    return {
        "duration": (date_from, date_to),
        "mtd": (mtd_start, mtd_end),
        "ytd": (fy_start, ref),
        "mtd_month_label": month_column_label(anchor),
    }


def sellable_room_count(layout):
    count = 0
    for room in (layout or {}).get("rooms") or []:
        if not isinstance(room, dict):
            continue
        if _normalize_hotel_room_status(room.get("status")) == "out_of_order":
            continue
        count += 1
    return count


def _empty_metrics():
    metrics = {
        "total_rooms": 0,
        "rooms_sold": 0,
        "pax": 0,
        "extra_person": 0,
        "revenue": 0.0,
    }
    for key in OCC_KEYS:
        metrics[key] = 0
    for plan in RATE_PLANS:
        metrics[f"{plan.lower()}_room"] = 0
        metrics[f"{plan.lower()}_pax"] = 0
    for key in PAY_KEYS:
        metrics[key] = 0.0
    return metrics


def _as_int(value, default=0):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _normalize_rate_plan(value):
    text = str(value or "").strip().upper()
    if not text:
        return "EP"
    token = text.replace("·", " ").replace("/", " ").split()[0]
    token = "".join(ch for ch in token if ch.isalpha())
    if token in RATE_PLANS:
        return token
    return "EP"


def _payment_bucket(method):
    key = str(method or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("bank", "bank_transfer", "banktransfer", "neft", "rtgs", "imps"):
        return "bank"
    if key == "cash":
        return "cash"
    if key in ("card", "credit_card", "debit_card"):
        return "card"
    if key == "upi":
        return "upi"
    if key in (
        "credit",
        "room_credit",
        "room_transfer",
        "company",
        "agent_credit",
        "agency_credit",
        "on_credit",
    ):
        return "credit"
    return ""


def _room_units(payload, stay):
    numbers = []
    for source in (
        payload.get("mergeRoomNumbers") if isinstance(payload, dict) else None,
        stay.get("mergeRoomNumbers") if isinstance(stay, dict) else None,
        stay.get("merge_room_numbers") if isinstance(stay, dict) else None,
    ):
        if isinstance(source, list) and source:
            numbers = source
            break
    cleaned = []
    seen = set()
    for raw in numbers:
        label = str(raw or "").strip()
        if not label or label in seen:
            continue
        seen.add(label)
        cleaned.append(label)
    if len(cleaned) >= 2:
        return len(cleaned)
    return 1


def _stay_nights(check_in, check_out):
    if not check_in or not check_out:
        return 1
    nights = (check_out - check_in).days
    return max(1, nights)


def _iter_occupied_nights(check_in, check_out, start, end):
    if not check_in or not check_out or not start or not end:
        return
    night = check_in
    while night < check_out:
        if start <= night <= end:
            yield night
        night += timedelta(days=1)


def _occupancy_types(pax, room_units):
    units = max(1, int(room_units or 1))
    guests = max(1, int(pax or 1))
    base = guests // units
    rem = guests % units
    for idx in range(units):
        occ = base + (1 if idx < rem else 0)
        occ = max(1, min(4, occ))
        if occ <= 1:
            yield "single"
        elif occ == 2:
            yield "double"
        elif occ == 3:
            yield "triple"
        else:
            yield "quad"


def _parse_payload(raw):
    if isinstance(raw, dict):
        return raw
    try:
        payload = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _stay_from_payload(payload):
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
    return stay if isinstance(stay, dict) else {}


def _stay_check_dates(stay, row=None):
    check_in = _hotel_parse_iso_date(
        stay.get("checkInDate") or stay.get("check_in_date")
    )
    check_out = _hotel_parse_iso_date(
        stay.get("checkOutDate") or stay.get("check_out_date")
    )
    if check_in is None and row is not None:
        check_in = _hotel_parse_iso_date(row.get("check_in_date"))
    if check_out is None and row is not None:
        check_out = _hotel_parse_iso_date(row.get("check_out_date"))
    if check_in is None:
        return None, None
    if check_out is None or check_out <= check_in:
        booked = max(1, _as_int(stay.get("nights") or stay.get("billableNights"), 1))
        check_out = check_in + timedelta(days=booked)
    return check_in, check_out


def _stay_revenue(stay, row=None):
    estimated = _as_float(
        stay.get("estimatedTotal")
        or stay.get("estimated_total")
        or (row.get("estimated_total") if row else 0)
    )
    if estimated > 0.005:
        return round(estimated, 2)
    total_rate = _as_float(stay.get("totalRate") or stay.get("total_rate"))
    if total_rate > 0.005:
        return round(total_rate, 2)
    nights = max(1, _as_int(stay.get("billableNights") or stay.get("nights"), 1))
    rate = _as_float(stay.get("roomRate") or stay.get("room_rate"))
    extra = _as_float(stay.get("extraBedAmount") or stay.get("extra_bed_amount"))
    return round(rate * nights + extra, 2)


def _stay_payments(stay, revenue):
    buckets = {key: 0.0 for key in PAY_KEYS}
    payments = stay.get("payments") if isinstance(stay.get("payments"), list) else []
    paid = 0.0
    if payments:
        for pay in payments:
            if not isinstance(pay, dict):
                continue
            amount = _as_float(pay.get("amount"))
            if abs(amount) < 0.005:
                continue
            bucket = _payment_bucket(
                pay.get("method")
                or pay.get("payment_method")
                or pay.get("paymentMethod")
            )
            if not bucket:
                continue
            buckets[bucket] += amount
            paid += amount
    else:
        method = stay.get("paymentMethod") or stay.get("payment_method") or ""
        advance = _as_float(
            stay.get("advancePaid")
            or stay.get("advance_paid")
            or stay.get("checkInAdvancePaid")
        )
        bucket = _payment_bucket(method)
        if bucket and advance > 0.005:
            buckets[bucket] += advance
            paid += advance
    unpaid = round(revenue - paid, 2)
    if unpaid > 0.005:
        buckets["credit"] += unpaid
    return buckets


def normalize_stay(payload, *, row=None, room_number=""):
    payload = _parse_payload(payload)
    stay = _stay_from_payload(payload)
    check_in, check_out = _stay_check_dates(stay, row)
    if check_in is None:
        return None
    adults = max(1, _as_int(stay.get("adults"), 1))
    children = max(0, _as_int(stay.get("children"), 0))
    pax = adults + children
    extra = max(0, _as_int(stay.get("extraBedQty") or stay.get("extra_bed_qty"), 0))
    plan = _normalize_rate_plan(stay.get("ratePlan") or stay.get("rate_plan"))
    invoice_number = str(
        stay.get("invoiceNumber")
        or stay.get("invoice_number")
        or (row.get("invoice_number") if row else "")
        or ""
    ).strip()
    number = str(
        payload.get("number")
        or room_number
        or (row.get("room_number") if row else "")
        or ""
    ).strip()
    units = _room_units(payload, stay)
    revenue = _stay_revenue(stay, row)
    return {
        "invoice_number": invoice_number,
        "room_number": number,
        "check_in": check_in,
        "check_out": check_out,
        "pax": pax,
        "extra_person": extra,
        "plan": plan,
        "room_units": units,
        "revenue": revenue,
        "payments": _stay_payments(stay, revenue),
        "merge_key": tuple(
            sorted(
                str(n).strip()
                for n in (
                    payload.get("mergeRoomNumbers")
                    or stay.get("mergeRoomNumbers")
                    or ([number] if number else [])
                )
                if str(n).strip()
            )
        ),
    }


def _stay_identity(item):
    if item.get("invoice_number"):
        return ("inv", item["invoice_number"])
    merge = item.get("merge_key") or ()
    check_in = item["check_in"].isoformat() if item.get("check_in") else ""
    if merge:
        return ("rooms", merge, check_in)
    return ("room", item.get("room_number") or "", check_in)


def metrics_for_window(stays, sellable_rooms, start, end):
    metrics = _empty_metrics()
    nights = period_nights(start, end)
    metrics["total_rooms"] = max(0, int(sellable_rooms or 0)) * nights
    if not start or not end or nights <= 0:
        return finalize_metrics(metrics)

    for stay in stays or []:
        occupied = list(
            _iter_occupied_nights(stay["check_in"], stay["check_out"], start, end)
        )
        if not occupied:
            continue
        occ_nights = len(occupied)
        units = max(1, int(stay.get("room_units") or 1))
        pax = max(1, int(stay.get("pax") or 1))
        plan = _normalize_rate_plan(stay.get("plan"))
        metrics["rooms_sold"] += occ_nights * units
        metrics["pax"] += occ_nights * pax
        metrics["extra_person"] += occ_nights * max(0, int(stay.get("extra_person") or 0))
        metrics[f"{plan.lower()}_room"] += occ_nights * units
        metrics[f"{plan.lower()}_pax"] += occ_nights * pax
        for _night in occupied:
            for occ_key in _occupancy_types(pax, units):
                metrics[occ_key] += 1
        stay_len = _stay_nights(stay["check_in"], stay["check_out"])
        share = occ_nights / float(stay_len)
        metrics["revenue"] += round(_as_float(stay.get("revenue")) * share, 2)
        payments = stay.get("payments") or {}
        for key in PAY_KEYS:
            metrics[key] += round(_as_float(payments.get(key)) * share, 2)

    return finalize_metrics(metrics)


def finalize_metrics(metrics):
    total_rooms = float(metrics.get("total_rooms") or 0)
    rooms_sold = float(metrics.get("rooms_sold") or 0)
    pax = float(metrics.get("pax") or 0)
    revenue = round(_as_float(metrics.get("revenue")), 2)
    metrics["revenue"] = revenue
    metrics["arr"] = round(revenue / rooms_sold, 2) if rooms_sold else 0.0
    metrics["arp"] = round(revenue / pax, 2) if pax else 0.0

    def _pct(count):
        if total_rooms <= 0:
            return 0.0
        return round((float(count or 0) / total_rooms) * 100.0, 2)

    metrics["pct_occupancy"] = _pct(metrics.get("rooms_sold"))
    metrics["pct_single"] = _pct(metrics.get("single"))
    metrics["pct_double"] = _pct(metrics.get("double"))
    metrics["pct_triple"] = _pct(metrics.get("triple"))
    metrics["pct_quad"] = _pct(metrics.get("quad"))
    for key in PAY_KEYS:
        metrics[key] = round(_as_float(metrics.get(key)), 2)
    return metrics


def build_report_rows(duration_metrics, mtd_metrics, ytd_metrics):
    rows = []
    for key, label, kind in ROW_SPECS:
        rows.append(
            {
                "key": key,
                "label": label,
                "kind": kind,
                "duration": duration_metrics.get(key, 0),
                "mtd": mtd_metrics.get(key, 0),
                "ytd": ytd_metrics.get(key, 0),
            }
        )
    return rows


def load_occupancy_stays(conn, window_start, window_end):
    """Stays whose nights overlap [window_start, window_end]."""
    ensure_hotel_room_invoices_schema(conn)
    backfill_hotel_room_invoices_from_layout(conn)
    start_s = window_start.isoformat()
    end_s = window_end.isoformat()
    rows = conn.execute(
        """
        SELECT invoice_number, room_number, check_in_date, check_out_date,
               estimated_total, payload_json
        FROM hotel_room_invoices
        WHERE (
              TRIM(COALESCE(check_in_date, '')) = ''
              OR substr(check_in_date, 1, 10) <= ?
          )
          AND (
            check_out_date IS NULL
            OR TRIM(check_out_date) = ''
            OR substr(check_out_date, 1, 10) > ?
          )
        """,
        (end_s, start_s),
    ).fetchall()

    stays = []
    seen = set()
    for row in rows:
        item = dict(row)
        stay = normalize_stay(item.get("payload_json"), row=item)
        if not stay:
            continue
        ident = _stay_identity(stay)
        if ident in seen:
            continue
        seen.add(ident)
        stays.append(stay)

    layout = get_hotel_rooms_layout(conn)
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        if not _hotel_room_has_inhouse_stay(room):
            continue
        stay = normalize_stay(room, room_number=str(room.get("number") or ""))
        if not stay:
            continue
        ident = _stay_identity(stay)
        if ident in seen:
            continue
        seen.add(ident)
        stays.append(stay)
    return stays, layout


def build_manager_insight(conn, *, date_from, date_to, today=None):
    ref = today or date.today()
    windows = manager_insight_windows(ref, date_from, date_to)
    date_windows = {
        key: windows[key] for key in ("duration", "mtd", "ytd")
    }
    widest_start = min(start for start, _end in date_windows.values() if start)
    widest_end = max(end for _start, end in date_windows.values() if end)
    stays, layout = load_occupancy_stays(conn, widest_start, widest_end)
    sellable = sellable_room_count(layout)
    duration_m = metrics_for_window(stays, sellable, *windows["duration"])
    mtd_m = metrics_for_window(stays, sellable, *windows["mtd"])
    ytd_m = metrics_for_window(stays, sellable, *windows["ytd"])
    return {
        "rows": build_report_rows(duration_m, mtd_m, ytd_m),
        "windows": windows,
        "mtd_month_label": windows.get("mtd_month_label") or "MTD",
        "sellable_rooms": sellable,
        "metrics": {
            "duration": duration_m,
            "mtd": mtd_m,
            "ytd": ytd_m,
        },
    }
