"""Asia Tech reservations provider adapter.

Live mode pulls bookings read-only via ``asia_tech_http`` when credentials exist.
Local creates, room assignments, and edits are stored in hotel settings under
``asia_tech_state``. Never pushes inventory, rates, or booking changes to Asia Tech.
"""

from __future__ import annotations

import copy
import hashlib
import os
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from asia_tech_http import DEFAULT_BASE_URL, clear_caches, fetch_bookings

MASKED_API_KEY = "••••••••••••••••"
STATUS_LABELS = {
    "upcoming": "Upcoming",
    "checked_in": "Checked In",
    "checked_out": "Checked Out",
    "cancelled": "Cancelled",
}
SOURCE_LABELS = {
    "booking_com": "Booking.com",
    "expedia": "Expedia",
    "makemytrip": "MakeMyTrip",
    "goibibo": "Goibibo",
    "agoda": "Agoda",
    "direct": "Direct",
    "walk_in": "Walk-in",
    "asia_tech": "Asia Tech",
}

_last_sync_meta: Dict[str, Any] = {
    "mode": "stub",
    "configured": False,
    "synced_at": "",
    "cached": False,
    "rooms_ok": False,
    "bookings_path": None,
    "error": "",
    "source": "stub",
}
_pending_provider_rows: List[Dict[str, Any]] = []


def _parse_iso(value: Any) -> Optional[date]:
    text = str(value or "").strip()
    if not text:
        return None
    # Drop time portion ("2026-08-24 14:00:00" / "24/08/2026 14:00").
    for sep in ("T", " "):
        if sep in text:
            text = text.split(sep, 1)[0].strip()
            break
    text = text[:10] if len(text) >= 10 and text[4] == "-" else text
    try:
        return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    for sep in ("-", "/", "."):
        parts = text.split(sep)
        if len(parts) == 3 and len(parts[2]) == 4:
            try:
                d, m, y = int(parts[0]), int(parts[1]), int(parts[2])
                if d > 31:
                    y, m, d = d, m, y
                return date(y, m, d)
            except ValueError:
                continue
    return None


def _nights(check_in: str, check_out: str) -> int:
    a = _parse_iso(check_in)
    b = _parse_iso(check_out)
    if not a or not b or b <= a:
        return 1
    return (b - a).days


def _total_rooms_from_raw(raw: Dict[str, Any]) -> int:
    explicit = _pick(
        raw,
        "totalRooms",
        "total_rooms",
        "noofrooms",
        "no_of_rooms",
        "NoOfRooms",
        "roomcount",
        "room_count",
        "rooms_count",
    )
    try:
        count = int(float(explicit or 0))
    except (TypeError, ValueError):
        count = 0
    rooms_val = raw.get("rooms")
    if count < 1 and isinstance(rooms_val, (int, float)) and not isinstance(rooms_val, bool):
        count = int(rooms_val)
    if count < 1:
        detail = raw.get("room_detail") or raw.get("roomdetail") or rooms_val
        if isinstance(detail, list) and detail:
            count = len(detail)
        elif isinstance(detail, dict) and detail:
            count = 1
    return max(1, count)


def _id_list_from_raw(value: Any) -> List[str]:
    items = value if isinstance(value, list) else []
    out: List[str] = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def assigned_room_ids(reservation: Any) -> List[str]:
    """Local room ids already on the booking, primary first."""
    row = reservation if isinstance(reservation, dict) else {}
    ids = _id_list_from_raw(row.get("roomIds") or row.get("room_ids"))
    primary = str(row.get("roomId") or row.get("room_id") or "").strip()
    if primary and primary not in ids:
        ids = [primary] + ids
    return ids


def assigned_room_numbers(reservation: Any) -> List[str]:
    row = reservation if isinstance(reservation, dict) else {}
    numbers = _id_list_from_raw(row.get("roomNumbers") or row.get("room_numbers"))
    number = str(row.get("roomNumber") or row.get("room_number") or "").strip()
    if number and number not in numbers:
        numbers = [number] + numbers
    return numbers


def assigned_room_count(reservation: Any) -> int:
    ids = assigned_room_ids(reservation)
    if ids:
        return len(ids)
    return len(assigned_room_numbers(reservation))


def reservation_total_rooms(reservation: Any) -> int:
    row = reservation if isinstance(reservation, dict) else {}
    try:
        count = int(float(row.get("totalRooms") or 1))
    except (TypeError, ValueError):
        count = 1
    return max(1, count)


def _initials(name: str) -> str:
    parts = [p for p in re.split(r"\s+", str(name or "").strip()) if p]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _money(value: Any, default: float = 0.0) -> float:
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return float(default)
    if amount != amount or amount < 0:
        return float(default)
    return round(amount, 2)


def _pick(row: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    lower_map = {str(k).lower(): v for k, v in row.items()}
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
        value = lower_map.get(str(key).lower())
        if value not in (None, ""):
            return value
    return default


def _stable_id(*parts: Any) -> str:
    raw = "|".join(str(p or "") for p in parts)
    return "AT-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def panel_value(settings: Dict[str, Any], key: str, default: str = "") -> str:
    panels = settings.get("panels") if isinstance(settings, dict) else None
    if not isinstance(panels, dict):
        return default
    panel = panels.get("asia_tech")
    if not isinstance(panel, dict):
        return default
    values = panel.get("values") if isinstance(panel.get("values"), dict) else panel
    if not isinstance(values, dict):
        return default
    field = values.get(key)
    if isinstance(field, dict):
        raw = field.get("value")
    else:
        raw = field
    if raw is None:
        return default
    return str(raw).strip()


def get_state(settings: Dict[str, Any]) -> Dict[str, Any]:
    state = settings.get("asia_tech_state") if isinstance(settings, dict) else None
    if not isinstance(state, dict):
        state = {}
    return {
        "api_key": str(state.get("api_key") or "").strip(),
        "password": str(state.get("password") or state.get("api_key") or "").strip(),
        "username": str(state.get("username") or "").strip(),
        "hotel_id": str(state.get("hotel_id") or "").strip(),
        "base_url": str(state.get("base_url") or "").strip(),
        "assignments": (
            dict(state["assignments"])
            if isinstance(state.get("assignments"), dict)
            else {}
        ),
        "overrides": (
            dict(state["overrides"]) if isinstance(state.get("overrides"), dict) else {}
        ),
        "created": (
            list(state["created"]) if isinstance(state.get("created"), list) else []
        ),
        "provider_rows": (
            list(state["provider_rows"])
            if isinstance(state.get("provider_rows"), list)
            else []
        ),
        "cm_email": str(state.get("cm_email") or "").strip(),
        "cm_password": str(state.get("cm_password") or "").strip(),
        "last_sync_meta": (
            dict(state["last_sync_meta"])
            if isinstance(state.get("last_sync_meta"), dict)
            else {}
        ),
    }


def _is_masked_secret(value: str) -> bool:
    text = str(value or "").strip()
    return (not text) or text == MASKED_API_KEY or set(text) <= {"•", "*"}


def get_api_key(settings: Dict[str, Any]) -> str:
    """Password / API key — env preferred, then panel, then state."""
    env = os.environ.get("ASIA_TECH_PASSWORD", "").strip()
    if env:
        return env
    key = panel_value(settings, "asia_tech_api_key", "")
    if not _is_masked_secret(key):
        return key
    password_panel = panel_value(settings, "asia_tech_password", "")
    if not _is_masked_secret(password_panel):
        return password_panel
    state = get_state(settings)
    return str(state.get("password") or state.get("api_key") or "").strip()


def get_username(settings: Dict[str, Any]) -> str:
    env = os.environ.get("ASIA_TECH_USERNAME", "").strip()
    if env:
        return env
    panel = panel_value(settings, "asia_tech_username", "")
    if panel:
        return panel
    return get_state(settings).get("username") or ""


def get_hotel_id(settings: Dict[str, Any]) -> str:
    env = os.environ.get("ASIA_TECH_HOTEL_ID", "").strip()
    if env:
        return env
    panel = panel_value(settings, "asia_tech_hotel_id", "")
    if panel:
        return panel
    return get_state(settings).get("hotel_id") or ""


def get_base_url(settings: Dict[str, Any]) -> str:
    from asia_tech_http import _normalize_base

    env = os.environ.get("ASIA_TECH_BASE_URL", "").strip()
    if env:
        return _normalize_base(env)
    panel = panel_value(settings, "asia_tech_base_url", "")
    if panel:
        return _normalize_base(panel)
    state_url = get_state(settings).get("base_url") or ""
    return _normalize_base(state_url or DEFAULT_BASE_URL)


def credentials_configured(settings: Dict[str, Any]) -> bool:
    return bool(get_username(settings) and get_api_key(settings) and get_hotel_id(settings))


def get_cm_email(settings: Dict[str, Any]) -> str:
    """Channel Manager browser login email (Booking Reports), not the JSON API user."""
    env = os.environ.get("ASIA_TECH_CM_EMAIL", "").strip()
    if env:
        return env
    panel = panel_value(settings, "asia_tech_cm_email", "")
    if panel:
        return panel
    return str(get_state(settings).get("cm_email") or "").strip()


def get_cm_password(settings: Dict[str, Any]) -> str:
    env = os.environ.get("ASIA_TECH_CM_PASSWORD", "").strip()
    if env:
        return env
    panel = panel_value(settings, "asia_tech_cm_password", "")
    if not _is_masked_secret(panel):
        return panel
    return str(get_state(settings).get("cm_password") or "").strip()


def cm_credentials_configured(settings: Dict[str, Any]) -> bool:
    return bool(get_cm_email(settings) and get_cm_password(settings))


def _persisted_provider_rows(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Saved Asia Tech rows, only if they belong to the current hotel."""
    state = get_state(settings)
    current = str(get_hotel_id(settings) or "").strip()
    stored = str(state.get("provider_hotel_id") or "").strip()
    if not current or stored != current:
        return []
    rows = state.get("provider_rows") or []
    return [row for row in rows if isinstance(row, dict)]


def get_mode(settings: Dict[str, Any]) -> str:
    mode = panel_value(settings, "asia_tech_mode", "stub").lower()
    if mode not in ("stub", "live"):
        mode = "stub"
    configured = credentials_configured(settings)
    # Env credentials on the server imply live pull when mode isn't forced stub…
    # but honor explicit stub for local demos. Auto-live when mode=live OR env triad present.
    env_live = bool(
        os.environ.get("ASIA_TECH_USERNAME", "").strip()
        and os.environ.get("ASIA_TECH_PASSWORD", "").strip()
        and os.environ.get("ASIA_TECH_HOTEL_ID", "").strip()
    )
    if not configured:
        return "stub"
    if mode == "live" or env_live:
        return "live"
    return "stub"


def get_last_sync_meta() -> Dict[str, Any]:
    return dict(_last_sync_meta)


def mask_settings_for_client(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy safe to send to the browser (API key / password masked)."""
    out = copy.deepcopy(settings) if isinstance(settings, dict) else {}
    state = get_state(out)
    has_key = bool(state.get("api_key") or state.get("password") or get_api_key(out))
    panels = out.setdefault("panels", {})
    if not isinstance(panels, dict):
        panels = {}
        out["panels"] = panels
    asia = panels.setdefault("asia_tech", {"values": {}})
    if not isinstance(asia, dict):
        asia = {"values": {}}
        panels["asia_tech"] = asia
    values = asia.setdefault("values", {})
    if not isinstance(values, dict):
        values = {}
        asia["values"] = values
    values["asia_tech_api_key"] = {
        "kind": "text",
        "value": MASKED_API_KEY if has_key else "",
    }
    values["asia_tech_password"] = {
        "kind": "text",
        "value": MASKED_API_KEY if has_key else "",
    }
    has_cm = bool(get_cm_password(out))
    values["asia_tech_cm_password"] = {
        "kind": "text",
        "value": MASKED_API_KEY if has_cm else "",
    }
    values["asia_tech_cm_email"] = {
        "kind": "text",
        "value": panel_value(out, "asia_tech_cm_email", get_cm_email(out)),
    }
    values["asia_tech_username"] = {
        "kind": "text",
        "value": panel_value(out, "asia_tech_username", get_username(out)),
    }
    values["asia_tech_hotel_id"] = {
        "kind": "text",
        "value": panel_value(out, "asia_tech_hotel_id", get_hotel_id(out)),
    }
    values["asia_tech_base_url"] = {
        "kind": "text",
        "value": panel_value(out, "asia_tech_base_url", get_base_url(out))
        or DEFAULT_BASE_URL,
    }
    if "asia_tech_mode" not in values:
        values["asia_tech_mode"] = {
            "kind": "text",
            "value": panel_value(out, "asia_tech_mode", "stub") or "stub",
        }
    if "asia_tech_state" in out and isinstance(out["asia_tech_state"], dict):
        safe_state = dict(out["asia_tech_state"])
        if safe_state.get("api_key") or safe_state.get("password"):
            safe_state["api_key"] = MASKED_API_KEY
            safe_state["password"] = MASKED_API_KEY
            safe_state["has_api_key"] = True
        else:
            safe_state["has_api_key"] = False
        if safe_state.get("cm_password"):
            safe_state["cm_password"] = MASKED_API_KEY
        out["asia_tech_state"] = safe_state
    out["asia_tech_has_api_key"] = has_key
    out["asia_tech_has_credentials"] = credentials_configured(out)
    out["asia_tech_mode_effective"] = get_mode(out)
    return out


def merge_settings_on_save(
    existing: Dict[str, Any], incoming: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge UI settings PUT with preserved Asia Tech secrets/state."""
    existing = existing if isinstance(existing, dict) else {}
    incoming = copy.deepcopy(incoming) if isinstance(incoming, dict) else {}

    if "asia_tech_state" not in incoming:
        if "asia_tech_state" in existing:
            incoming["asia_tech_state"] = copy.deepcopy(existing["asia_tech_state"])
    else:
        prev = get_state(existing)
        nxt = get_state(incoming)
        incoming["asia_tech_state"] = {
            "api_key": nxt.get("api_key") or prev.get("api_key") or "",
            "password": nxt.get("password") or nxt.get("api_key") or prev.get("password") or prev.get("api_key") or "",
            "username": nxt.get("username") or prev.get("username") or "",
            "hotel_id": nxt.get("hotel_id") or prev.get("hotel_id") or "",
            "base_url": nxt.get("base_url") or prev.get("base_url") or "",
            "assignments": nxt.get("assignments") or prev.get("assignments") or {},
            "overrides": nxt.get("overrides") or prev.get("overrides") or {},
            "created": nxt.get("created") if nxt.get("created") is not None else prev.get("created") or [],
            "provider_rows": (
                nxt.get("provider_rows")
                if nxt.get("provider_rows") is not None
                else prev.get("provider_rows") or []
            ),
            "last_sync_meta": nxt.get("last_sync_meta") or prev.get("last_sync_meta") or {},
        }

    in_panels = incoming.get("panels") if isinstance(incoming.get("panels"), dict) else {}
    asia = in_panels.get("asia_tech") if isinstance(in_panels.get("asia_tech"), dict) else {}
    values = asia.get("values") if isinstance(asia.get("values"), dict) else {}

    def _submitted(key: str) -> str:
        if not isinstance(values, dict) or key not in values:
            return ""
        field = values.get(key)
        return (
            str(field.get("value") or "").strip()
            if isinstance(field, dict)
            else str(field or "").strip()
        )

    prev_state = get_state(existing)
    prev_key = prev_state.get("password") or prev_state.get("api_key") or ""
    if not prev_key:
        prev_key = panel_value(existing, "asia_tech_api_key", "")
        if _is_masked_secret(prev_key):
            prev_key = ""

    submitted_key = _submitted("asia_tech_api_key")
    submitted_password = _submitted("asia_tech_password")
    secret = prev_key
    for candidate in (submitted_password, submitted_key):
        if candidate and not _is_masked_secret(candidate):
            secret = candidate
            break

    prev_cm_password = str(prev_state.get("cm_password") or "").strip()
    if not prev_cm_password:
        prev_cm_password = panel_value(existing, "asia_tech_cm_password", "")
        if _is_masked_secret(prev_cm_password):
            prev_cm_password = ""
    submitted_cm_password = _submitted("asia_tech_cm_password")
    cm_password = prev_cm_password
    if submitted_cm_password and not _is_masked_secret(submitted_cm_password):
        cm_password = submitted_cm_password
    cm_email = (
        _submitted("asia_tech_cm_email")
        or prev_state.get("cm_email")
        or panel_value(existing, "asia_tech_cm_email", "")
        or ""
    )

    username = _submitted("asia_tech_username") or prev_state.get("username") or ""
    hotel_id = _submitted("asia_tech_hotel_id") or prev_state.get("hotel_id") or ""
    base_url = _submitted("asia_tech_base_url") or prev_state.get("base_url") or DEFAULT_BASE_URL

    state = get_state(incoming)
    state["api_key"] = secret
    state["password"] = secret
    state["username"] = username
    state["hotel_id"] = hotel_id
    state["base_url"] = base_url
    state["cm_email"] = cm_email
    state["cm_password"] = cm_password
    incoming["asia_tech_state"] = state

    if isinstance(values, dict):
        values["asia_tech_api_key"] = {
            "kind": "text",
            "value": MASKED_API_KEY if secret else "",
        }
        values["asia_tech_password"] = {
            "kind": "text",
            "value": MASKED_API_KEY if secret else "",
        }
        values["asia_tech_cm_password"] = {
            "kind": "text",
            "value": MASKED_API_KEY if cm_password else "",
        }
        values["asia_tech_cm_email"] = {"kind": "text", "value": cm_email}
        values["asia_tech_username"] = {"kind": "text", "value": username}
        values["asia_tech_hotel_id"] = {"kind": "text", "value": hotel_id}
        values["asia_tech_base_url"] = {
            "kind": "text",
            "value": base_url or DEFAULT_BASE_URL,
        }
        asia["values"] = values
        in_panels["asia_tech"] = asia
        incoming["panels"] = in_panels

    clear_caches()
    return incoming


def update_state(settings: Dict[str, Any], **patches: Any) -> Dict[str, Any]:
    out = copy.deepcopy(settings) if isinstance(settings, dict) else {}
    state = get_state(out)
    for key, value in patches.items():
        state[key] = value
    out["asia_tech_state"] = state
    return out


def _stub_seed() -> List[Dict[str, Any]]:
    """Provider seed rows when not in live mode."""
    return []


def _map_status(raw: Any) -> str:
    status = str(raw or "upcoming").strip().lower().replace(" ", "_").replace("-", "_")
    aliases = {
        "confirmed": "upcoming",
        "confirm": "upcoming",
        "booked": "upcoming",
        "reservation": "upcoming",
        "reserved": "upcoming",
        "upcoming": "upcoming",
        "modified": "upcoming",
        "checkedin": "checked_in",
        "checked_in": "checked_in",
        "checkin": "checked_in",
        "in_house": "checked_in",
        "inhouse": "checked_in",
        "checkedout": "checked_out",
        "checked_out": "checked_out",
        "checkout": "checked_out",
        "departed": "checked_out",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "cancel": "cancelled",
        "no_show": "cancelled",
        "noshow": "cancelled",
    }
    mapped = aliases.get(status, status)
    if mapped not in STATUS_LABELS:
        return "upcoming"
    return mapped


def _derive_operational_status(
    status: str,
    check_in: str,
    check_out: str,
    *,
    today: Optional[date] = None,
) -> str:
    """
    Asia Tech getbooking often returns only confirmed/cancelled.
    Infer checked_in / checked_out / upcoming from the stay window vs today.
    """
    if status == "cancelled":
        return "cancelled"
    if status in ("checked_in", "checked_out"):
        return status
    today = today or date.today()
    cin = _parse_iso(check_in)
    cout = _parse_iso(check_out)
    if not cin or not cout:
        return status if status in STATUS_LABELS else "upcoming"
    if cin <= today < cout:
        return "checked_in"
    if cout <= today:
        return "checked_out"
    return "upcoming"


def _map_source(raw: Any) -> str:
    source = str(raw or "asia_tech").strip().lower()
    compact = re.sub(r"[^a-z0-9]+", "_", source).strip("_")
    aliases = {
        "booking_com": "booking_com",
        "bookingcom": "booking_com",
        "booking": "booking_com",
        "expedia": "expedia",
        "makemytrip": "makemytrip",
        "mmt": "makemytrip",
        "goibibo": "goibibo",
        "agoda": "agoda",
        "direct": "direct",
        "offline_booking": "direct",
        "offline": "direct",
        "walk_in": "walk_in",
        "walkin": "walk_in",
        "asia_tech": "asia_tech",
        "asiatech": "asia_tech",
    }
    return aliases.get(compact, compact or "asia_tech")


def _room_label_from_raw(raw: Dict[str, Any]) -> str:
    detail = raw.get("room_detail") or raw.get("roomdetail") or raw.get("rooms")
    if isinstance(detail, list) and detail:
        first = detail[0] if isinstance(detail[0], dict) else {}
        label = str(
            first.get("roomname")
            or first.get("room_name")
            or first.get("roomtype")
            or first.get("RoomName")
            or ""
        ).strip()
        if label:
            return label
    return str(
        _pick(
            raw,
            "roomTypeLabel",
            "room_type_label",
            "roomType",
            "RoomType",
            "roomname",
            "RoomName",
            "room",
            default="",
        )
        or ""
    ).strip()


MEAL_PLAN_LABELS = {
    "ep": "Room only",
    "cp": "Breakfast",
    "map": "Breakfast & dinner",
    "ap": "All meals",
    "ai": "All inclusive",
    "bb": "Bed & breakfast",
}


def _format_meal_plan(code: str) -> str:
    text = str(code or "").strip()
    if not text:
        return ""
    friendly = MEAL_PLAN_LABELS.get(text.lower())
    if friendly and friendly.lower() != text.lower():
        return f"{text} · {friendly}"
    return text


def _meal_plan_from_raw(raw: Dict[str, Any]) -> str:
    codes: List[str] = []
    seen = set()
    detail = raw.get("room_detail") or raw.get("roomdetail") or raw.get("rooms")
    if isinstance(detail, list):
        for item in detail:
            if not isinstance(item, dict):
                continue
            code = str(item.get("mealplan") or item.get("meal_plan") or item.get("MealPlan") or "").strip()
            key = code.lower()
            if code and key not in seen:
                seen.add(key)
                codes.append(code)
    if not codes:
        code = str(
            _pick(raw, "mealPlan", "mealplan", "meal_plan", "MealPlan", default="") or ""
        ).strip()
        if code:
            codes.append(code)
    return ", ".join(_format_meal_plan(code) for code in codes if code)


def _special_notes_from_raw(raw: Dict[str, Any]) -> str:
    return str(
        _pick(
            raw,
            "specialNotes",
            "special_notes",
            "guestinfo",
            "guest_info",
            "guestInfo",
            "specialrequest",
            "special_request",
            "remarks",
            "notes",
            "comment",
            default="",
        )
        or ""
    ).strip()


def _map_payment(raw: Any) -> str:
    if isinstance(raw, (int, float)):
        # Asia Tech getbooking: paymentstatus 1 ≈ paid.
        return "paid" if int(raw) == 1 else "pending"
    text = str(raw or "pending").strip().lower()
    if text in ("1", "paid", "success", "complete", "completed"):
        return "paid"
    if text in ("partial", "part"):
        return "partial"
    if text in ("refunded", "refund"):
        return "refunded"
    return "pending"


def _normalize_reservation(raw: Dict[str, Any]) -> Dict[str, Any]:
    guest_name = str(
        _pick(
            raw,
            "guestName",
            "guest_name",
            "GuestName",
            "guestname",
            "customerName",
            "CustomerName",
            "name",
            default="",
        )
    ).strip()
    booking_id = str(
        _pick(
            raw,
            "bookingId",
            "booking_id",
            "BookingId",
            "bookingid",
            "reservationId",
            "reservation_id",
            "ReservationId",
            "id",
            default="",
        )
    ).strip()
    check_in_raw = _pick(
        raw,
        "checkInDate",
        "check_in_date",
        "check_in",
        "checkin",
        "CheckIn",
        "arrival",
        "ArrivalDate",
        "from_date",
    )
    check_out_raw = _pick(
        raw,
        "checkOutDate",
        "check_out_date",
        "check_out",
        "checkout",
        "CheckOut",
        "departure",
        "DepartureDate",
        "to_date",
    )
    cin = _parse_iso(check_in_raw)
    cout = _parse_iso(check_out_raw)
    check_in = cin.isoformat() if cin else str(check_in_raw or "")[:10]
    check_out = cout.isoformat() if cout else str(check_out_raw or "")[:10]
    status = _map_status(
        _pick(
            raw,
            "status",
            "Status",
            "bookingstatus",
            "booking_status",
            "BookingStatus",
        )
    )
    status = _derive_operational_status(status, check_in, check_out)
    source = _map_source(
        _pick(
            raw,
            "source",
            "Source",
            "bookingsource",
            "booking_source",
            "channel",
            "Channel",
            "ota",
            "OTA",
            "booked_by",
        )
    )
    amount = _money(
        _pick(
            raw,
            "amount",
            "totalrate",
            "total_rate",
            "TotalRate",
            "totalAmount",
            "total_amount",
            "TotalAmount",
            "price",
            "Price",
            "total",
            "Total",
        )
    )
    nights = int(_pick(raw, "nights", "Nights", default=0) or 0) or _nights(check_in, check_out)
    room_number = str(
        _pick(raw, "roomNumber", "room_number", "RoomNumber", "assigned_room", default="")
    ).strip()
    room_label = _room_label_from_raw(raw)
    room_id = str(_pick(raw, "roomId", "room_id", default="") or "").strip()
    room_ids = _id_list_from_raw(raw.get("roomIds") or raw.get("room_ids"))
    if room_id and room_id not in room_ids:
        room_ids = [room_id] + room_ids
    room_numbers = _id_list_from_raw(raw.get("roomNumbers") or raw.get("room_numbers"))
    if room_number and room_number not in room_numbers:
        room_numbers = [room_number] + room_numbers
    payment = _map_payment(
        _pick(raw, "paymentStatus", "payment_status", "PaymentStatus", "paymentstatus", default="pending")
    )
    if not booking_id:
        booking_id = _stable_id(guest_name, check_in, check_out, room_label, amount)
    guests = int(
        _money(
            _pick(raw, "guests", "guestCount", "pax", "Pax", "adults", "Adults", default=1)
        )
        or 1
    )
    if guests < 1:
        guests = 1
    return {
        "id": booking_id,
        "bookingId": booking_id,
        "guestName": guest_name or "Guest",
        "initials": _initials(guest_name or "Guest"),
        "mobile": str(
            _pick(
                raw,
                "mobile",
                "phone",
                "Phone",
                "Mobile",
                "guestmobile",
                "guest_mobile",
                "guest_phone",
                default="",
            )
        ).strip(),
        "email": str(
            _pick(raw, "email", "Email", "guestemail", "guest_email", default="") or ""
        ).strip(),
        "guests": guests,
        "checkInDate": check_in,
        "checkInTime": str(_pick(raw, "checkInTime", "check_in_time", default="14:00") or "14:00"),
        "checkOutDate": check_out,
        "checkOutTime": str(
            _pick(raw, "checkOutTime", "check_out_time", default="11:00") or "11:00"
        ),
        "nights": nights,
        "totalRooms": _total_rooms_from_raw(raw),
        "roomId": room_id,
        "roomIds": room_ids,
        "roomNumber": room_number,
        "roomNumbers": room_numbers,
        "roomTypeLabel": room_label,
        "roomAssigned": bool(room_number or room_ids),
        "amount": amount,
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, status.title()),
        "source": source,
        "sourceLabel": SOURCE_LABELS.get(source, source.replace("_", " ").title()),
        "paymentStatus": payment,
        "paymentStatusLabel": payment.replace("_", " ").title(),
        "mealPlan": _meal_plan_from_raw(raw),
        "specialNotes": _special_notes_from_raw(raw),
        "provider": str(raw.get("provider") or "asia_tech"),
    }


def _apply_local_state(
    rows: List[Dict[str, Any]], settings: Dict[str, Any]
) -> List[Dict[str, Any]]:
    state = get_state(settings)
    by_id = {r["id"]: r for r in rows}
    for item in state.get("created") or []:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_reservation(item)
        by_id[normalized["id"]] = normalized
    for res_id, override in (state.get("overrides") or {}).items():
        if not isinstance(override, dict):
            continue
        base = by_id.get(str(res_id)) or {"id": str(res_id), "bookingId": str(res_id)}
        merged = dict(base)
        merged.update(override)
        by_id[str(res_id)] = _normalize_reservation(merged)
    for res_id, assignment in (state.get("assignments") or {}).items():
        if not isinstance(assignment, dict):
            continue
        base = by_id.get(str(res_id))
        if not base:
            continue
        merged = dict(base)
        merged["roomId"] = assignment.get("roomId") or merged.get("roomId")
        merged["roomIds"] = assignment.get("roomIds") or merged.get("roomIds") or []
        merged["roomNumber"] = assignment.get("roomNumber") or merged.get("roomNumber")
        merged["roomNumbers"] = (
            assignment.get("roomNumbers") or merged.get("roomNumbers") or []
        )
        merged["roomTypeLabel"] = (
            assignment.get("roomTypeLabel") or merged.get("roomTypeLabel") or ""
        )
        by_id[str(res_id)] = _normalize_reservation(merged)
    return list(by_id.values())


def list_provider_reservations(
    settings: Dict[str, Any],
    *,
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """List reservations; live mode fetches Asia Tech read-only when configured."""
    global _last_sync_meta, _pending_provider_rows
    _pending_provider_rows = []
    mode = get_mode(settings)
    meta: Dict[str, Any] = {
        "mode": mode,
        "configured": credentials_configured(settings),
        "synced_at": "",
        "cached": False,
        "rooms_ok": False,
        "bookings_path": None,
        "error": "",
        "source": "stub",
        "base_url": get_base_url(settings),
    }
    seed: List[Dict[str, Any]] = []
    prior_raw = _persisted_provider_rows(settings)
    if mode == "live":
        if prior_raw:
            from asia_tech_http import merge_booking_rows

            merge_booking_rows(
                [row for row in prior_raw if isinstance(row, dict)],
                cred_key="|".join(
                    [
                        get_base_url(settings),
                        get_username(settings),
                        get_hotel_id(settings),
                    ]
                ),
            )
        raw_rows, http_meta = fetch_bookings(
            base_url=get_base_url(settings),
            username=get_username(settings),
            password=get_api_key(settings),
            hotel_id=get_hotel_id(settings),
            force_refresh=force_refresh,
        )
        meta.update(
            {
                "synced_at": http_meta.get("synced_at") or "",
                "cached": bool(http_meta.get("cached")),
                "rooms_ok": bool(http_meta.get("rooms_ok")),
                "bookings_path": http_meta.get("bookings_path"),
                "error": http_meta.get("error") or "",
                "source": "asia_tech",
                "base_url": http_meta.get("base_url") or get_base_url(settings),
                "fromdate": http_meta.get("fromdate") or "",
                "todate": http_meta.get("todate") or "",
                "pulled": int(http_meta.get("pulled") or 0),
            }
        )
        if not meta["error"]:
            meta["coverage"] = (
                "Asia Tech only sends bookings created or updated in the last "
                "10 days. Older stays show here after they are saved again "
                "in Asia Tech."
            )
        if cm_credentials_configured(settings):
            try:
                from asia_tech_cm import fetch_checkin_booking_reports
                from asia_tech_http import merge_booking_rows

                cm_rows, cm_meta = fetch_checkin_booking_reports(
                    email=get_cm_email(settings),
                    password=get_cm_password(settings),
                )
                meta["cm_ok"] = bool(cm_meta.get("cm_ok"))
                meta["cm_pulled"] = int(cm_meta.get("cm_pulled") or 0)
                meta["cm_error"] = str(cm_meta.get("cm_error") or "")
                if cm_rows:
                    raw_rows = merge_booking_rows(
                        list(raw_rows) + list(cm_rows),
                        cred_key="|".join(
                            [
                                get_base_url(settings),
                                get_username(settings),
                                get_hotel_id(settings),
                            ]
                        ),
                    )
                    meta["bookings_path"] = (
                        str(meta.get("bookings_path") or "")
                        + "+cm/booking-reports"
                    ).strip("+")
            except Exception as exc:  # pragma: no cover - network/runtime guard
                meta["cm_ok"] = False
                meta["cm_error"] = str(exc)[:240]
        elif not meta.get("error"):
            meta["cm_hint"] = (
                "Add Asia Tech Channel Manager email/password to sync by "
                "check-in date (Bookings → Booking Reports), including older stays."
            )

        seed = [_normalize_reservation(r) for r in raw_rows if isinstance(r, dict)]
        by_id = {row["id"]: row for row in seed if row.get("id")}
        for item in prior_raw:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_reservation(item)
            rid = str(normalized.get("id") or "")
            if rid and rid not in by_id:
                by_id[rid] = normalized
        seed = list(by_id.values())
        if meta.get("cm_ok") and int(meta.get("cm_pulled") or 0) > 0:
            meta["coverage"] = (
                "Synced Asia Tech Booking Report by check-in date, plus recent "
                "API activity."
            )
        elif meta.get("cm_error") and not meta.get("error"):
            meta["error"] = (
                "Asia Tech Booking Report (check-in) sync failed: "
                + str(meta.get("cm_error"))
            )
        elif meta.get("cm_hint") and not meta.get("error"):
            # Keep coverage note; do not treat missing CM login as a hard error.
            meta["coverage"] = (
                str(meta.get("coverage") or "")
                + (" " if meta.get("coverage") else "")
                + str(meta["cm_hint"])
            ).strip()
    else:
        seed = list(_stub_seed())
        meta["source"] = "stub"

    _last_sync_meta = meta
    _pending_provider_rows = list(seed) if mode == "live" else []
    return _apply_local_state(seed, settings)


_PROVIDER_ROW_KEYS = (
    "id",
    "bookingId",
    "guestName",
    "checkInDate",
    "checkOutDate",
    "status",
    "source",
    "amount",
    "mobile",
    "email",
    "guests",
    "roomTypeLabel",
    "roomNumber",
    "roomId",
    "roomIds",
    "paymentStatus",
    "nights",
    "totalRooms",
    "mealPlan",
    "specialNotes",
    "provider",
    "roomNumbers",
)


def persist_provider_rows(settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Return updated settings when the live booking snapshot gained rows."""
    global _pending_provider_rows
    rows = list(_pending_provider_rows)
    _pending_provider_rows = []
    if not rows:
        return None
    compact = []
    for row in rows:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        compact.append({key: row.get(key) for key in _PROVIDER_ROW_KEYS})
    prev = get_state(settings).get("provider_rows") or []
    prev_ids = {
        str(item.get("id") or "")
        for item in prev
        if isinstance(item, dict) and item.get("id")
    }
    new_ids = {str(item.get("id") or "") for item in compact}
    if new_ids <= prev_ids and len(prev) >= len(compact):
        prev_hotel = str(get_state(settings).get("provider_hotel_id") or "").strip()
        if prev_hotel == str(get_hotel_id(settings) or "").strip():
            return None
    return update_state(
        settings,
        provider_rows=compact,
        provider_hotel_id=str(get_hotel_id(settings) or "").strip(),
    )


def compute_kpis(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(rows)
    checked_in = sum(1 for r in rows if r.get("status") == "checked_in")
    upcoming = sum(1 for r in rows if r.get("status") == "upcoming")
    checked_out = sum(1 for r in rows if r.get("status") == "checked_out")
    revenue = round(sum(_money(r.get("amount")) for r in rows), 2)
    return {
        "total": total,
        "checked_in": checked_in,
        "upcoming": upcoming,
        "checked_out": checked_out,
        "revenue": revenue,
    }


def _resolve_filter_dates(
    *,
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
) -> Tuple[Optional[date], Optional[date]]:
    d_from = _parse_iso(date_from)
    d_to = _parse_iso(date_to)
    day = _parse_iso(on_date)
    if day and not d_from and not d_to:
        d_from = day
        d_to = day
    if d_from and not d_to:
        d_to = d_from
    if d_to and not d_from:
        d_from = d_to
    if d_from and d_to and d_from > d_to:
        d_from, d_to = d_to, d_from
    return d_from, d_to


def count_checkouts_for_date(
    rows: List[Dict[str, Any]],
    *,
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
) -> int:
    """Count expected checkouts whose departure date falls in the selected range.

    A stay with check-out on 12 Aug is counted for 12 Aug even though stay
    overlap treats checkout day as exclusive (so the table/Total omit them).
    Cancelled bookings are excluded. When no date is selected, count all
    currently checked-out rows.
    """
    d_from, d_to = _resolve_filter_dates(
        on_date=on_date, date_from=date_from, date_to=date_to
    )
    if not d_from or not d_to:
        return sum(1 for r in rows if r.get("status") == "checked_out")
    count = 0
    for row in rows:
        if row.get("status") == "cancelled":
            continue
        cout = _parse_iso(row.get("checkOutDate"))
        if cout and d_from <= cout <= d_to:
            count += 1
    return count


def count_upcoming_for_date(
    rows: List[Dict[str, Any]],
    *,
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
) -> int:
    """Count stays for the selected date that are still pending check-in.

    This is the upcoming subset of Total Reservations (stay overlap). When no
    date is selected, count all upcoming rows.
    """
    d_from, d_to = _resolve_filter_dates(
        on_date=on_date, date_from=date_from, date_to=date_to
    )
    if not d_from or not d_to:
        return sum(1 for r in rows if r.get("status") == "upcoming")
    overlapping = filter_reservations(
        rows,
        date_from=d_from.isoformat(),
        date_to=d_to.isoformat(),
    )
    return sum(1 for row in overlapping if row.get("status") == "upcoming")


def count_checked_in_for_date(
    rows: List[Dict[str, Any]],
    *,
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
) -> int:
    """Count guests in-house during the selected date range.

    Occupancy is check-in through the night before checkout. When no date is
    selected, count all currently checked-in rows.
    """
    d_from, d_to = _resolve_filter_dates(
        on_date=on_date, date_from=date_from, date_to=date_to
    )
    if not d_from or not d_to:
        return sum(1 for r in rows if r.get("status") == "checked_in")
    count = 0
    for row in rows:
        if row.get("status") == "cancelled":
            continue
        cin = _parse_iso(row.get("checkInDate"))
        cout = _parse_iso(row.get("checkOutDate"))
        if not cin or not cout:
            continue
        if cin <= d_to and cout > d_from:
            count += 1
    return count


def filter_reservations(
    rows: List[Dict[str, Any]],
    *,
    q: str = "",
    status: str = "all",
    source: str = "all",
    on_date: str = "",
    date_from: str = "",
    date_to: str = "",
    checkout_only: bool = False,
) -> List[Dict[str, Any]]:
    needle = str(q or "").strip().lower()
    status = str(status or "all").strip().lower()
    source = str(source or "all").strip().lower()
    checkout_only = bool(checkout_only)
    d_from, d_to = _resolve_filter_dates(
        on_date=on_date, date_from=date_from, date_to=date_to
    )
    out: List[Dict[str, Any]] = []
    for row in rows:
        if source != "all" and row.get("source") != source:
            continue
        if checkout_only:
            # Match the Checked Out KPI: expected departures on the selected
            # date(s), including in-house guests leaving that day.
            if d_from and d_to:
                if row.get("status") == "cancelled":
                    continue
                cout = _parse_iso(row.get("checkOutDate"))
                if not cout or not (d_from <= cout <= d_to):
                    continue
            elif row.get("status") != "checked_out":
                continue
        else:
            if status != "all" and row.get("status") != status:
                continue
            if d_from and d_to:
                cin = _parse_iso(row.get("checkInDate"))
                cout = _parse_iso(row.get("checkOutDate"))
                if not cin:
                    continue
                if cout:
                    # Stay covers [from, to], including checkout day so CHECK OUT
                    # column dates for the selected day remain visible.
                    if not (cin <= d_to and cout >= d_from):
                        continue
                elif not (d_from <= cin <= d_to):
                    # Incomplete vendor row: still show on the check-in date.
                    continue
        if needle:
            blob = " ".join(
                [
                    str(row.get("guestName") or ""),
                    str(row.get("bookingId") or ""),
                    str(row.get("mobile") or ""),
                    str(row.get("email") or ""),
                    str(row.get("roomNumber") or ""),
                ]
            ).lower()
            if needle not in blob:
                continue
        out.append(row)
    out.sort(key=lambda r: (r.get("checkInDate") or "", r.get("bookingId") or ""))
    return out


def paginate(
    rows: List[Dict[str, Any]], page: int = 1, page_size: int = 5
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        page = max(1, int(page))
    except (TypeError, ValueError):
        page = 1
    raw_size = str(page_size or "").strip().lower()
    if raw_size in ("", "all", "0"):
        page_size = 0
    else:
        try:
            page_size = int(page_size)
        except (TypeError, ValueError):
            page_size = 5
        if page_size < 0:
            page_size = 5
    total = len(rows)
    if page_size == 0 or page_size >= total:
        return rows, {
            "page": 1,
            "pageSize": total,
            "total": total,
            "totalPages": 1,
            "from": 1 if total else 0,
            "to": total,
            "scroll": True,
        }
    if page_size not in (5, 10, 20, 50, 100, 500):
        page_size = 5
    pages = max(1, (total + page_size - 1) // page_size) if total else 1
    if page > pages:
        page = pages
    start = (page - 1) * page_size
    end = start + page_size
    slice_rows = rows[start:end]
    return slice_rows, {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": pages,
        "from": (start + 1) if total else 0,
        "to": min(end, total),
        "scroll": False,
    }


def get_reservation(settings: Dict[str, Any], reservation_id: str) -> Optional[Dict[str, Any]]:
    rid = str(reservation_id or "").strip()
    for row in list_provider_reservations(settings):
        if row.get("id") == rid or row.get("bookingId") == rid:
            return row
    return None


def create_reservation(
    settings: Dict[str, Any], payload: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    state = get_state(settings)
    created = list(state.get("created") or [])
    seq = len(created) + 1
    booking_id = str(payload.get("bookingId") or payload.get("id") or "").strip()
    if not booking_id:
        booking_id = f"RES-2026-{seq:03d}"
    item = _normalize_reservation(
        {
            **(payload if isinstance(payload, dict) else {}),
            "id": booking_id,
            "bookingId": booking_id,
            "status": payload.get("status") or "upcoming",
            "source": payload.get("source") or "direct",
            "provider": "asia_tech",
        }
    )
    created.append(item)
    next_settings = update_state(settings, created=created)
    return item, next_settings


def update_reservation(
    settings: Dict[str, Any], reservation_id: str, payload: Dict[str, Any]
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    current = get_reservation(settings, reservation_id)
    if not current:
        raise ValueError("Reservation not found.")
    merged = dict(current)
    if isinstance(payload, dict):
        merged.update(payload)
    merged["id"] = current["id"]
    merged["bookingId"] = current["bookingId"]
    normalized = _normalize_reservation(merged)
    state = get_state(settings)
    overrides = dict(state.get("overrides") or {})
    overrides[normalized["id"]] = normalized
    created = []
    for item in state.get("created") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or item.get("bookingId") or "") == normalized["id"]:
            created.append(normalized)
        else:
            created.append(item)
    next_settings = update_state(settings, overrides=overrides, created=created)
    return normalized, next_settings


def assign_room_local(
    settings: Dict[str, Any],
    reservation_id: str,
    *,
    room_id: str,
    room_number: str,
    room_type_label: str = "",
    room_ids: Optional[List[str]] = None,
    room_numbers: Optional[List[str]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    current = get_reservation(settings, reservation_id)
    if not current:
        raise ValueError("Reservation not found.")
    if current.get("status") == "checked_out":
        raise ValueError("Cannot assign a room to a checked-out reservation.")
    state = get_state(settings)
    assignments = dict(state.get("assignments") or {})
    existing_ids = assigned_room_ids(current)
    existing_numbers = assigned_room_numbers(current)
    incoming_ids = _id_list_from_raw(room_ids)
    incoming_primary = str(room_id or "").strip()
    if incoming_primary and incoming_primary not in incoming_ids:
        incoming_ids = [incoming_primary] + incoming_ids
    incoming_numbers = _id_list_from_raw(room_numbers)
    incoming_number = str(room_number or "").strip()
    if incoming_number and incoming_number not in incoming_numbers:
        incoming_numbers = [incoming_number] + incoming_numbers

    if existing_ids:
        primary_id = existing_ids[0]
        ids = list(existing_ids)
        for rid in incoming_ids:
            if rid not in ids:
                ids.append(rid)
        primary_number = str(current.get("roomNumber") or "").strip() or incoming_number
        label = str(current.get("roomTypeLabel") or "").strip() or str(
            room_type_label or ""
        ).strip()
    else:
        primary_id = incoming_primary or (incoming_ids[0] if incoming_ids else "")
        ids = list(incoming_ids)
        if primary_id and primary_id not in ids:
            ids = [primary_id] + ids
        primary_number = incoming_number
        label = str(room_type_label or "").strip()

    numbers = list(existing_numbers)
    for num in incoming_numbers:
        if num not in numbers:
            numbers.append(num)
    if primary_number and primary_number not in numbers:
        numbers = [primary_number] + numbers

    assignment = {
        "roomId": primary_id,
        "roomNumber": primary_number,
        "roomTypeLabel": label,
    }
    if ids:
        assignment["roomIds"] = ids
    if numbers:
        assignment["roomNumbers"] = numbers
    assignments[current["id"]] = assignment
    next_settings = update_state(settings, assignments=assignments)
    updated = get_reservation(next_settings, current["id"])
    return updated or current, next_settings
