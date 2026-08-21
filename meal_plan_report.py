"""Meal Plan report — in-house rooms with dining covers by meal plan."""

from __future__ import annotations

import json
from datetime import date

from db import (
    _hotel_parse_iso_date,
    _hotel_room_has_inhouse_stay,
    backfill_hotel_room_invoices_from_layout,
    ensure_hotel_room_invoices_schema,
    get_hotel_rooms_layout,
)
from manager_insight import (
    _as_int,
    _normalize_rate_plan,
    _room_units,
    _stay_check_dates,
)

RATE_PLANS = ("EP", "CP", "MAP", "AP")

RATE_PLAN_LABELS = {
    "EP": "EP — Room Only",
    "CP": "CP — Breakfast",
    "MAP": "MAP — Breakfast + Dinner",
    "AP": "AP — All Meals",
}

# Meals included per canonical rate / meal plan.
MEAL_INCLUSIONS = {
    "EP": {"breakfast": False, "lunch": False, "dinner": False},
    "CP": {"breakfast": True, "lunch": False, "dinner": False},
    "MAP": {"breakfast": True, "lunch": False, "dinner": True},
    "AP": {"breakfast": True, "lunch": True, "dinner": True},
}


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


def _guest_name(stay, row=None):
    if isinstance(stay, dict):
        name = str(stay.get("guestName") or stay.get("guest_name") or "").strip()
        if name:
            return name
        first = str(stay.get("firstName") or stay.get("first_name") or "").strip()
        last = str(stay.get("lastName") or stay.get("last_name") or "").strip()
        combined = f"{first} {last}".strip()
        if combined:
            return combined
    if row is not None:
        return str(row.get("guest_name") or "").strip()
    return ""


def _room_label(payload, stay, room_number=""):
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
        return " + ".join(cleaned)
    primary = str(
        room_number
        or (payload.get("number") if isinstance(payload, dict) else "")
        or ""
    ).strip()
    return primary or (cleaned[0] if cleaned else "")


def plan_for_date(stay, report_date):
    """Rate plan for a specific night; nightly override wins over stay-level."""
    if not isinstance(stay, dict) or not report_date:
        return _normalize_rate_plan(None)
    target = report_date.isoformat()
    nightly = stay.get("nightlyRates") or stay.get("nightly_rates") or []
    if isinstance(nightly, list):
        for row in nightly:
            if not isinstance(row, dict):
                continue
            night = _hotel_parse_iso_date(row.get("date") or row.get("night"))
            if night is None:
                continue
            if night.isoformat() != target:
                continue
            plan = row.get("ratePlan") or row.get("rate_plan")
            if str(plan or "").strip():
                return _normalize_rate_plan(plan)
    return _normalize_rate_plan(stay.get("ratePlan") or stay.get("rate_plan"))


def meal_covers_for_plan(plan, pax):
    guests = max(0, int(pax or 0))
    code = _normalize_rate_plan(plan)
    flags = MEAL_INCLUSIONS.get(code) or MEAL_INCLUSIONS["EP"]
    return {
        "breakfast": guests if flags["breakfast"] else 0,
        "lunch": guests if flags["lunch"] else 0,
        "dinner": guests if flags["dinner"] else 0,
    }


def _normalize_row(payload, *, row=None, room_number="", report_date=None):
    payload = _parse_payload(payload)
    stay = _stay_from_payload(payload)
    check_in, check_out = _stay_check_dates(stay, row)
    if check_in is None or report_date is None:
        return None
    if not (check_in <= report_date < check_out):
        return None
    adults = max(1, _as_int(stay.get("adults"), 1))
    children = max(0, _as_int(stay.get("children"), 0))
    pax = adults + children
    plan = plan_for_date(stay, report_date)
    covers = meal_covers_for_plan(plan, pax)
    number = _room_label(
        payload,
        stay,
        room_number=room_number
        or (str((row or {}).get("room_number") or "") if row else ""),
    )
    units = _room_units(payload, stay)
    invoice_number = str(
        stay.get("invoiceNumber")
        or stay.get("invoice_number")
        or ((row or {}).get("invoice_number") if row else "")
        or ""
    ).strip()
    return {
        "invoice_number": invoice_number,
        "room_number": number,
        "guest_name": _guest_name(stay, row),
        "check_in": check_in,
        "check_out": check_out,
        "adults": adults,
        "children": children,
        "pax": pax,
        "plan": plan,
        "plan_label": RATE_PLAN_LABELS.get(plan, plan),
        "breakfast": covers["breakfast"],
        "lunch": covers["lunch"],
        "dinner": covers["dinner"],
        "room_units": units,
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


def _room_sort_key(label):
    text = str(label or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    try:
        return (0, int(digits or 0), text.lower())
    except ValueError:
        return (1, 0, text.lower())


def _meal_plan_identity(item):
    """One dining row per room / merge set for the night (ignore invoice churn)."""
    merge = item.get("merge_key") or ()
    cleaned = tuple(str(n).strip() for n in merge if str(n).strip())
    if len(cleaned) >= 2:
        return ("rooms", tuple(sorted(cleaned, key=_room_sort_key)))
    room = str(item.get("room_number") or "").strip().lower()
    if " + " in room:
        parts = tuple(
            sorted(
                (p.strip() for p in room.split("+") if p.strip()),
                key=_room_sort_key,
            )
        )
        if len(parts) >= 2:
            return ("rooms", parts)
    return ("room", room)


def load_meal_plan_rows(conn, report_date):
    """Deduped in-house stays occupied on report_date (layout preferred)."""
    ensure_hotel_room_invoices_schema(conn)
    backfill_hotel_room_invoices_from_layout(conn)

    items = []
    seen = set()

    def _add(normalized):
        if not normalized:
            return
        ident = _meal_plan_identity(normalized)
        if not ident[1] or ident in seen:
            return
        seen.add(ident)
        items.append(normalized)

    # Live layout first — source of truth for currently occupied rooms.
    layout = get_hotel_rooms_layout(conn)
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        if not _hotel_room_has_inhouse_stay(room):
            continue
        _add(
            _normalize_row(
                room,
                room_number=str(room.get("number") or ""),
                report_date=report_date,
            )
        )

    day_s = report_date.isoformat()
    rows = conn.execute(
        """
        SELECT invoice_number, room_number, guest_name, check_in_date, check_out_date,
               estimated_total, payload_json,
               COALESCE(NULLIF(TRIM(updated_at), ''), NULLIF(TRIM(invoice_generated_at), ''), '') AS sort_ts
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
        ORDER BY sort_ts DESC
        """,
        (day_s, day_s),
    ).fetchall()

    for row in rows:
        item = dict(row)
        _add(
            _normalize_row(
                item.get("payload_json"), row=item, report_date=report_date
            )
        )

    items.sort(key=lambda r: _room_sort_key(r.get("room_number")))
    return items


def summarize_meal_plan(rows):
    kpis = {
        "occupied_rooms": 0,
        "total_pax": 0,
        "breakfast": 0,
        "lunch": 0,
        "dinner": 0,
    }
    for code in RATE_PLANS:
        kpis[f"{code.lower()}_rooms"] = 0
        kpis[f"{code.lower()}_pax"] = 0
    for row in rows or []:
        units = max(1, int(row.get("room_units") or 1))
        pax = max(0, int(row.get("pax") or 0))
        plan = _normalize_rate_plan(row.get("plan"))
        kpis["occupied_rooms"] += units
        kpis["total_pax"] += pax
        kpis["breakfast"] += int(row.get("breakfast") or 0)
        kpis["lunch"] += int(row.get("lunch") or 0)
        kpis["dinner"] += int(row.get("dinner") or 0)
        kpis[f"{plan.lower()}_rooms"] += units
        kpis[f"{plan.lower()}_pax"] += pax
    return kpis


def build_meal_plan_report(conn, *, report_date=None, today=None):
    ref = today or date.today()
    day = report_date or ref
    rows = load_meal_plan_rows(conn, day)
    return {
        "rows": rows,
        "kpis": summarize_meal_plan(rows),
        "report_date": day,
        "today": ref,
    }
