"""Asia Tech reservations provider adapter.

Until Asia Tech publishes API docs, ``mode=stub`` (default) starts with an empty
reservation list. Live HTTP calls are reserved for when credentials + endpoints
exist. Local creates, room assignments, and edits are stored in hotel settings
under ``asia_tech_state`` so they survive settings panel saves.
"""

from __future__ import annotations

import copy
import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

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
    "direct": "Direct",
    "walk_in": "Walk-in",
    "asia_tech": "Asia Tech",
}


def _parse_iso(value: Any) -> Optional[date]:
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _nights(check_in: str, check_out: str) -> int:
    a = _parse_iso(check_in)
    b = _parse_iso(check_out)
    if not a or not b or b <= a:
        return 1
    return (b - a).days


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


def get_api_key(settings: Dict[str, Any]) -> str:
    key = panel_value(settings, "asia_tech_api_key", "")
    if not key or key == MASKED_API_KEY or set(key) <= {"•", "*"}:
        # Fall back to top-level secret if panels only have a mask.
        state = settings.get("asia_tech_state") if isinstance(settings, dict) else None
        if isinstance(state, dict):
            secret = str(state.get("api_key") or "").strip()
            if secret:
                return secret
        return ""
    return key


def get_base_url(settings: Dict[str, Any]) -> str:
    return panel_value(settings, "asia_tech_base_url", "") or "https://api.asiatech.in"


def get_mode(settings: Dict[str, Any]) -> str:
    mode = panel_value(settings, "asia_tech_mode", "stub").lower()
    if mode not in ("stub", "live"):
        return "stub"
    # Live requires a real key; otherwise stay on stub.
    if mode == "live" and not get_api_key(settings):
        return "stub"
    return mode


def get_state(settings: Dict[str, Any]) -> Dict[str, Any]:
    state = settings.get("asia_tech_state") if isinstance(settings, dict) else None
    if not isinstance(state, dict):
        state = {}
    return {
        "api_key": str(state.get("api_key") or "").strip(),
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
    }


def mask_settings_for_client(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy safe to send to the browser (API key masked)."""
    out = copy.deepcopy(settings) if isinstance(settings, dict) else {}
    state = get_state(out)
    has_key = bool(state.get("api_key") or get_api_key(out))
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
    if "asia_tech_base_url" not in values:
        values["asia_tech_base_url"] = {
            "kind": "text",
            "value": panel_value(out, "asia_tech_base_url", get_base_url(out)),
        }
    if "asia_tech_mode" not in values:
        values["asia_tech_mode"] = {
            "kind": "text",
            "value": panel_value(out, "asia_tech_mode", "stub") or "stub",
        }
    # Never expose raw secret in asia_tech_state to the client.
    if "asia_tech_state" in out and isinstance(out["asia_tech_state"], dict):
        safe_state = dict(out["asia_tech_state"])
        if safe_state.get("api_key"):
            safe_state["api_key"] = MASKED_API_KEY
            safe_state["has_api_key"] = True
        else:
            safe_state["has_api_key"] = False
        out["asia_tech_state"] = safe_state
    out["asia_tech_has_api_key"] = has_key
    out["asia_tech_mode_effective"] = get_mode(out)
    return out


def merge_settings_on_save(
    existing: Dict[str, Any], incoming: Dict[str, Any]
) -> Dict[str, Any]:
    """Merge UI settings PUT with preserved Asia Tech secrets/state."""
    existing = existing if isinstance(existing, dict) else {}
    incoming = copy.deepcopy(incoming) if isinstance(incoming, dict) else {}

    # Preserve runtime state unless caller explicitly replaces it.
    if "asia_tech_state" not in incoming:
        if "asia_tech_state" in existing:
            incoming["asia_tech_state"] = copy.deepcopy(existing["asia_tech_state"])
    else:
        # Merge nested assignment maps rather than clobbering blindly if partial.
        prev = get_state(existing)
        nxt = get_state(incoming)
        incoming["asia_tech_state"] = {
            "api_key": nxt.get("api_key") or prev.get("api_key") or "",
            "assignments": nxt.get("assignments") or prev.get("assignments") or {},
            "overrides": nxt.get("overrides") or prev.get("overrides") or {},
            "created": nxt.get("created") if nxt.get("created") is not None else prev.get("created") or [],
        }

    # Panel API key: keep previous secret when masked/empty.
    in_panels = incoming.get("panels") if isinstance(incoming.get("panels"), dict) else {}
    asia = in_panels.get("asia_tech") if isinstance(in_panels.get("asia_tech"), dict) else {}
    values = asia.get("values") if isinstance(asia.get("values"), dict) else {}
    submitted = ""
    if isinstance(values, dict) and "asia_tech_api_key" in values:
        field = values.get("asia_tech_api_key")
        submitted = (
            str(field.get("value") or "").strip()
            if isinstance(field, dict)
            else str(field or "").strip()
        )
    prev_key = get_state(existing).get("api_key") or ""
    # Also recover from previously stored panel if state empty (legacy).
    if not prev_key:
        prev_key = panel_value(existing, "asia_tech_api_key", "")
        if prev_key == MASKED_API_KEY or set(prev_key) <= {"•", "*"}:
            prev_key = ""

    secret = prev_key
    if submitted and submitted != MASKED_API_KEY and not (set(submitted) <= {"•", "*"}):
        secret = submitted

    state = get_state(incoming)
    state["api_key"] = secret
    incoming["asia_tech_state"] = state

    if isinstance(values, dict):
        values["asia_tech_api_key"] = {
            "kind": "text",
            "value": MASKED_API_KEY if secret else "",
        }
        asia["values"] = values
        in_panels["asia_tech"] = asia
        incoming["panels"] = in_panels

    return incoming


def update_state(settings: Dict[str, Any], **patches: Any) -> Dict[str, Any]:
    out = copy.deepcopy(settings) if isinstance(settings, dict) else {}
    state = get_state(out)
    for key, value in patches.items():
        state[key] = value
    out["asia_tech_state"] = state
    return out


def _stub_seed() -> List[Dict[str, Any]]:
    """Provider seed rows. Empty until the live Asia Tech API is wired."""
    return []


def _normalize_reservation(raw: Dict[str, Any]) -> Dict[str, Any]:
    guest_name = str(raw.get("guestName") or raw.get("guest_name") or "").strip()
    booking_id = str(
        raw.get("bookingId") or raw.get("booking_id") or raw.get("id") or ""
    ).strip()
    check_in = str(raw.get("checkInDate") or raw.get("check_in_date") or "")[:10]
    check_out = str(raw.get("checkOutDate") or raw.get("check_out_date") or "")[:10]
    status = str(raw.get("status") or "upcoming").strip().lower().replace(" ", "_")
    if status in ("checkedin", "in_house", "inhouse"):
        status = "checked_in"
    if status in ("checkedout", "departed"):
        status = "checked_out"
    if status not in STATUS_LABELS:
        status = "upcoming"
    source = str(raw.get("source") or "asia_tech").strip().lower()
    amount = _money(raw.get("amount") or raw.get("totalAmount") or raw.get("price"))
    nights = int(raw.get("nights") or _nights(check_in, check_out))
    room_number = str(raw.get("roomNumber") or raw.get("room_number") or "").strip()
    room_label = str(
        raw.get("roomTypeLabel") or raw.get("room_type_label") or raw.get("roomType") or ""
    ).strip()
    payment = str(raw.get("paymentStatus") or raw.get("payment_status") or "pending").lower()
    if payment not in ("paid", "pending", "partial", "refunded"):
        payment = "pending"
    return {
        "id": booking_id,
        "bookingId": booking_id,
        "guestName": guest_name,
        "initials": _initials(guest_name),
        "mobile": str(raw.get("mobile") or raw.get("phone") or "").strip(),
        "email": str(raw.get("email") or "").strip(),
        "guests": int(raw.get("guests") or raw.get("guestCount") or 1),
        "checkInDate": check_in,
        "checkInTime": str(raw.get("checkInTime") or "14:00"),
        "checkOutDate": check_out,
        "checkOutTime": str(raw.get("checkOutTime") or "11:00"),
        "nights": nights,
        "roomId": str(raw.get("roomId") or raw.get("room_id") or "").strip(),
        "roomNumber": room_number,
        "roomTypeLabel": room_label,
        "roomAssigned": bool(room_number),
        "amount": amount,
        "status": status,
        "statusLabel": STATUS_LABELS.get(status, status.title()),
        "source": source,
        "sourceLabel": SOURCE_LABELS.get(source, source.replace("_", " ").title()),
        "paymentStatus": payment,
        "paymentStatusLabel": payment.replace("_", " ").title(),
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
        merged["roomNumber"] = assignment.get("roomNumber") or merged.get("roomNumber")
        merged["roomTypeLabel"] = (
            assignment.get("roomTypeLabel") or merged.get("roomTypeLabel") or ""
        )
        by_id[str(res_id)] = _normalize_reservation(merged)
    return list(by_id.values())


def list_provider_reservations(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    # Live HTTP reserved until Asia Tech endpoints are wired; local-only rows for now.
    return _apply_local_state(_stub_seed(), settings)


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


def filter_reservations(
    rows: List[Dict[str, Any]],
    *,
    q: str = "",
    status: str = "all",
    source: str = "all",
    on_date: str = "",
) -> List[Dict[str, Any]]:
    needle = str(q or "").strip().lower()
    status = str(status or "all").strip().lower()
    source = str(source or "all").strip().lower()
    day = _parse_iso(on_date)
    out: List[Dict[str, Any]] = []
    for row in rows:
        if status != "all" and row.get("status") != status:
            continue
        if source != "all" and row.get("source") != source:
            continue
        if day:
            cin = _parse_iso(row.get("checkInDate"))
            cout = _parse_iso(row.get("checkOutDate"))
            if not cin or not cout:
                continue
            # Inclusive stay window for the selected date (checkout day exclusive).
            if not (cin <= day < cout or cin == day):
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
    # Also update created list if it originated there.
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
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    current = get_reservation(settings, reservation_id)
    if not current:
        raise ValueError("Reservation not found.")
    if current.get("status") == "checked_out":
        raise ValueError("Cannot assign a room to a checked-out reservation.")
    state = get_state(settings)
    assignments = dict(state.get("assignments") or {})
    assignments[current["id"]] = {
        "roomId": str(room_id or "").strip(),
        "roomNumber": str(room_number or "").strip(),
        "roomTypeLabel": str(room_type_label or "").strip(),
    }
    next_settings = update_state(settings, assignments=assignments)
    updated = get_reservation(next_settings, current["id"])
    return updated or current, next_settings
