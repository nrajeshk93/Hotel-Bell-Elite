"""Read-only HTTP client for Asia Tech Extranet API.

Uses body-auth POSTs against ``provider.asiatech.in``.
HTTP (port 80) times out from many networks; HTTPS is required.
Never implements inventory/rate/booking write/update endpoints.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import requests

log = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://provider.asiatech.in"
REQUEST_TIMEOUT_S = 12
DISCOVERY_TIMEOUT_S = 6

# Documented read endpoints.
ROOMS_PATH = "/json/rooms"
INV_AND_RATE_PATH = "/json/getinvandrate"

# Live bookings pull (undocumented in rooms/rates PDF; verified read-only).
# Requires fromdate/todate; vendor only returns bookings from the past ~240 hours.
GETBOOKING_PATH = "/json/getbooking"
BOOKING_LOOKBACK_DAYS = 9  # stay under 240-hour vendor window

# Fallback discovery allowlist (same body-auth style).
BOOKING_PATH_CANDIDATES = (
    GETBOOKING_PATH,
    "/json/bookings",
    "/json/reservations",
    "/json/getbookings",
    "/json/bookinglist",
    "/json/getreservation",
    "/json/getreservations",
    "/json/booking",
    "/json/reservationlist",
)

# In-process discovery + list cache (per process / gunicorn worker).
_discovered_bookings_path: Optional[str] = None
_discovery_attempted = False
_list_cache: Dict[str, Any] = {"key": "", "at": 0.0, "rows": [], "meta": {}}
LIST_CACHE_TTL_S = 60.0


def _normalize_base(url: str) -> str:
    """Normalize base URL; force HTTPS for provider.asiatech.in (HTTP connects time out)."""
    base = str(url or "").strip().rstrip("/") or DEFAULT_BASE_URL
    parsed = urlparse(base if "://" in base else f"https://{base}")
    host = (parsed.hostname or "").lower()
    scheme = (parsed.scheme or "https").lower()
    if host in ("provider.asiatech.in", "www.provider.asiatech.in") and scheme == "http":
        parsed = parsed._replace(scheme="https")
        base = urlunparse(parsed).rstrip("/")
    elif not parsed.scheme:
        base = "https://" + base.lstrip("/")
    return base or DEFAULT_BASE_URL


def _friendly_net_error(exc_text: str) -> str:
    text = str(exc_text or "").strip()
    low = text.lower()
    if "connecttimeout" in low or "timed out" in low or "max retries exceeded" in low:
        return (
            "Cannot reach Asia Tech (connection timed out). "
            "Use https://provider.asiatech.in — plain HTTP on port 80 is blocked."
        )
    if "name or service not known" in low or "nodename nor servname" in low:
        return "Cannot resolve Asia Tech host. Check ASIA_TECH_BASE_URL."
    return text[:280]


def auth_body(
    *,
    username: str,
    password: str,
    hotel_id: str | int,
    **extra: Any,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "username": str(username or "").strip(),
        "password": str(password or "").strip(),
        "hotelid": int(hotel_id) if str(hotel_id).strip().isdigit() else hotel_id,
    }
    for key, value in extra.items():
        if value is not None and value != "":
            body[key] = value
    return body


def booking_date_window(today: Optional[date] = None) -> Tuple[str, str]:
    """Return (fromdate, todate) ISO strings within Asia Tech's ~240h lookback."""
    end = today or date.today()
    start = end - timedelta(days=BOOKING_LOOKBACK_DAYS)
    return start.isoformat(), end.isoformat()


def post_json(
    base_url: str,
    path: str,
    body: Dict[str, Any],
    *,
    timeout: float = REQUEST_TIMEOUT_S,
) -> Tuple[int, Any, str]:
    """POST JSON; returns (status_code, parsed_json_or_None, error_text)."""
    url = _normalize_base(base_url) + path
    try:
        response = requests.post(
            url,
            json=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return 0, None, _friendly_net_error(str(exc))
    text = ""
    try:
        text = response.text or ""
    except Exception:
        text = ""
    try:
        payload = response.json()
    except ValueError:
        payload = None
    err = ""
    if isinstance(payload, dict) and payload.get("error"):
        err = str(payload.get("error"))
    elif response.status_code >= 400:
        err = text[:280] or f"HTTP {response.status_code}"
    return response.status_code, payload, err


def fetch_rooms(
    *,
    base_url: str,
    username: str,
    password: str,
    hotel_id: str | int,
) -> Tuple[bool, Any, str]:
    """Verify credentials via documented /json/rooms. Returns (ok, payload, error)."""
    status, payload, err_text = post_json(
        base_url,
        ROOMS_PATH,
        auth_body(username=username, password=password, hotel_id=hotel_id),
    )
    if status != 200 or not isinstance(payload, dict):
        return False, payload, err_text or f"rooms HTTP {status}"
    if payload.get("room_list") is None and payload.get("error"):
        return False, payload, str(payload.get("error"))
    return True, payload, ""


def _looks_like_booking_list(payload: Any) -> List[Dict[str, Any]]:
    """Extract a list of booking-like dicts from a vendor payload, if any."""
    if isinstance(payload, list):
        rows = [r for r in payload if isinstance(r, dict)]
        return rows if rows else []
    if not isinstance(payload, dict):
        return []
    for key in (
        "bookings",
        "booking_list",
        "bookinglist",
        "reservations",
        "reservation_list",
        "reservationlist",
        "data",
        "result",
        "records",
        "list",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            rows = [r for r in value if isinstance(r, dict)]
            if rows:
                return rows
        if isinstance(value, dict):
            nested = _looks_like_booking_list(value)
            if nested:
                return nested
    if any(
        k in payload
        for k in (
            "guestname",
            "guest_name",
            "GuestName",
            "checkin",
            "check_in",
            "CheckIn",
            "bookingid",
            "BookingId",
            "reservationid",
        )
    ):
        return [payload]
    return []


def _getbooking_body(
    *,
    username: str,
    password: str,
    hotel_id: str | int,
) -> Dict[str, Any]:
    fromdate, todate = booking_date_window()
    return auth_body(
        username=username,
        password=password,
        hotel_id=hotel_id,
        fromdate=fromdate,
        todate=todate,
    )


def fetch_getbooking(
    *,
    base_url: str,
    username: str,
    password: str,
    hotel_id: str | int,
) -> Tuple[List[Dict[str, Any]], str]:
    """Pull bookings via /json/getbooking (read-only). Returns (rows, error)."""
    status, payload, err_text = post_json(
        base_url,
        GETBOOKING_PATH,
        _getbooking_body(username=username, password=password, hotel_id=hotel_id),
    )
    if status == 0:
        return [], err_text or "network error"
    if status != 200:
        return [], err_text or f"getbooking HTTP {status}"
    if isinstance(payload, dict) and payload.get("error"):
        return [], str(payload.get("error"))
    rows = _looks_like_booking_list(payload)
    return rows, ""


def discover_bookings_path(
    *,
    base_url: str,
    username: str,
    password: str,
    hotel_id: str | int,
    force: bool = False,
) -> Tuple[Optional[str], str]:
    """Prefer /json/getbooking; otherwise try allowlisted read paths."""
    global _discovered_bookings_path, _discovery_attempted
    if _discovered_bookings_path and not force:
        return _discovered_bookings_path, ""
    if _discovery_attempted and not force:
        return None, "No Asia Tech bookings endpoint discovered."
    _discovery_attempted = True

    rows, err = fetch_getbooking(
        base_url=base_url,
        username=username,
        password=password,
        hotel_id=hotel_id,
    )
    if rows or err == "":
        # Empty list with no error still counts as a working path.
        if not err:
            _discovered_bookings_path = GETBOOKING_PATH
            log.info("Asia Tech bookings path: %s (%s rows)", GETBOOKING_PATH, len(rows))
            return GETBOOKING_PATH, ""
        # "Required fields" without dates means path exists but our call failed oddly.
        if "fromdate" in err.lower() or "required fields" in err.lower():
            _discovered_bookings_path = GETBOOKING_PATH
            return GETBOOKING_PATH, ""

    errors: List[str] = [f"{GETBOOKING_PATH}:{err or 'empty'}"]
    body = auth_body(username=username, password=password, hotel_id=hotel_id)
    for path in BOOKING_PATH_CANDIDATES:
        if path == GETBOOKING_PATH:
            continue
        status, payload, err_text = post_json(
            base_url, path, body, timeout=DISCOVERY_TIMEOUT_S
        )
        if status == 404:
            errors.append(f"{path}:404")
            continue
        if status == 0:
            errors.append(f"{path}:net")
            continue
        found = _looks_like_booking_list(payload)
        if status == 200 and found:
            _discovered_bookings_path = path
            log.info("Asia Tech bookings path discovered: %s (%s rows)", path, len(found))
            return path, ""
        errors.append(f"{path}:{status}")
    return None, (
        "Asia Tech bookings endpoint not available — ask vendor for reservations API. "
        f"Tried: {', '.join(errors[:8])}"
    )


def fetch_bookings(
    *,
    base_url: str,
    username: str,
    password: str,
    hotel_id: str | int,
    force_refresh: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Fetch booking rows (read-only).

    Returns (rows, meta) where meta includes synced_at, path, error, rooms_ok.
    """
    global _list_cache
    base = _normalize_base(base_url)
    cred_key = f"{base}|{username}|{hotel_id}"
    now = time.monotonic()
    if (
        not force_refresh
        and _list_cache.get("key") == cred_key
        and (now - float(_list_cache.get("at") or 0)) < LIST_CACHE_TTL_S
    ):
        meta = dict(_list_cache.get("meta") or {})
        meta["cached"] = True
        return list(_list_cache.get("rows") or []), meta

    meta: Dict[str, Any] = {
        "cached": False,
        "synced_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "base_url": base,
        "rooms_ok": False,
        "bookings_path": None,
        "error": "",
        "fromdate": "",
        "todate": "",
    }
    fromdate, todate = booking_date_window()
    meta["fromdate"] = fromdate
    meta["todate"] = todate

    rooms_ok, _rooms_payload, rooms_err = fetch_rooms(
        base_url=base,
        username=username,
        password=password,
        hotel_id=hotel_id,
    )
    meta["rooms_ok"] = rooms_ok
    if not rooms_ok:
        meta["error"] = (
            "Asia Tech credentials failed on /json/rooms: "
            + (rooms_err or "unknown error")
        )
        _list_cache = {"key": cred_key, "at": now, "rows": [], "meta": meta}
        return [], meta

    # Fast path: known getbooking endpoint with date window.
    rows, get_err = fetch_getbooking(
        base_url=base,
        username=username,
        password=password,
        hotel_id=hotel_id,
    )
    if not get_err:
        meta["bookings_path"] = GETBOOKING_PATH
        _discovered_bookings_path_set(GETBOOKING_PATH)
        _list_cache = {"key": cred_key, "at": now, "rows": rows, "meta": meta}
        return rows, meta

    path, discover_err = discover_bookings_path(
        base_url=base,
        username=username,
        password=password,
        hotel_id=hotel_id,
        force=force_refresh,
    )
    meta["bookings_path"] = path
    if not path:
        meta["error"] = get_err or discover_err
        _list_cache = {"key": cred_key, "at": now, "rows": [], "meta": meta}
        return [], meta

    if path == GETBOOKING_PATH:
        rows, err = fetch_getbooking(
            base_url=base,
            username=username,
            password=password,
            hotel_id=hotel_id,
        )
        if err:
            meta["error"] = err
            rows = []
    else:
        status, payload, err_text = post_json(
            base,
            path,
            auth_body(username=username, password=password, hotel_id=hotel_id),
        )
        rows = _looks_like_booking_list(payload) if status == 200 else []
        if status != 200:
            meta["error"] = err_text or f"bookings HTTP {status}"
            rows = []

    _list_cache = {"key": cred_key, "at": now, "rows": rows, "meta": meta}
    return rows, meta


def _discovered_bookings_path_set(path: str) -> None:
    global _discovered_bookings_path, _discovery_attempted
    _discovered_bookings_path = path
    _discovery_attempted = True


def clear_caches() -> None:
    global _discovered_bookings_path, _discovery_attempted, _list_cache
    _discovered_bookings_path = None
    _discovery_attempted = False
    _list_cache = {"key": "", "at": 0.0, "rows": [], "meta": {}}
