"""Read-only Asia Tech Channel Manager Booking Report client.

Matches the admin UI flow:
  Bookings → Booking Reports → Booking Type (Check In) → Date → Search

This is separate from ``provider.asiatech.in/json/getbooking``, which only
returns bookings created/updated in the last ~240 hours. The CM report can
list stays by check-in date regardless of when they were last saved.

Requires Channel Manager admin email/password (browser login), not the
provider JSON API username.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta
from html import unescape
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urljoin

import requests

log = logging.getLogger(__name__)

CM_ADMIN_BASE = "https://www.asiatech.in/booking_engine/admin/"
CM_LOGIN_PATH = "login"
CM_LOGIN_AJAX = "ajaxrequest/loginphp.php"
CM_REPORT_PAGE = "booking-reports"
CM_REPORT_AJAX = "ajaxrequest/booking-reports.php"
REQUEST_TIMEOUT_S = 20
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
)

# Days of check-in dates to pull around today (inclusive).
CM_CHECKIN_PAST_DAYS = 1
CM_CHECKIN_FUTURE_DAYS = 21


def _strip_tags(html: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html or "")
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</t[dh]>", "\t", text)
    text = re.sub(r"(?is)</tr>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def _parse_report_date(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(text[:20], fmt).date().isoformat()
        except ValueError:
            continue
    # "13-Aug-2026" / "13 Aug, 2026"
    cleaned = text.replace(",", "")
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(cleaned[:20], fmt).date().isoformat()
        except ValueError:
            continue
    return ""


def format_querydate(day: date) -> str:
    """Asia Tech booking-reports datepicker format (dd-mm-yy)."""
    return day.strftime("%d-%m-%Y")


def checkin_report_dates(today: Optional[date] = None) -> List[date]:
    """Dates to query as Check In on the CM booking report."""
    day = today or date.today()
    start = day - timedelta(days=CM_CHECKIN_PAST_DAYS)
    end = day + timedelta(days=CM_CHECKIN_FUTURE_DAYS)
    out: List[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def parse_booking_report_html(html: str) -> List[Dict[str, Any]]:
    """Parse Booking Report HTML table rows into getbooking-like dicts."""
    text = str(html or "")
    if not text.strip():
        return []
    rows: List[Dict[str, Any]] = []
    seen = set()

    # Prefer real table rows when present.
    for tr in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", text):
        cells = [
            _strip_tags(cell).strip()
            for cell in re.findall(r"(?is)<t[dh][^>]*>(.*?)</t[dh]>", tr)
        ]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue
        blob = " | ".join(cells)
        bid_match = re.search(r"(FDR\d{8,})", blob, re.I)
        if not bid_match:
            continue
        booking_id = bid_match.group(1).upper()
        if booking_id in seen:
            continue
        guest = ""
        for cell in cells:
            if booking_id.lower() in cell.lower():
                continue
            if re.search(r"\d{1,2}[-/ ]\w{3,}[-/ ]\d{2,4}|\d{4}-\d{2}-\d{2}", cell):
                continue
            if re.search(r"^(confirmed|cancelled|canceled|check\s*in|check\s*out)$", cell, re.I):
                continue
            if re.fullmatch(r"[\d,.]+", cell.replace("₹", "").strip()):
                continue
            if len(cell) >= 2 and not guest:
                guest = cell
        dates = re.findall(
            r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}-\d{2}-\d{2}|\d{1,2}[- ][A-Za-z]{3,}[-, ]+\d{2,4})",
            blob,
        )
        check_in = _parse_report_date(dates[0]) if dates else ""
        check_out = _parse_report_date(dates[1]) if len(dates) > 1 else ""
        amount = 0.0
        money = re.findall(r"(?:₹\s*)?([\d,]+(?:\.\d+)?)", blob)
        if money:
            try:
                amount = float(money[-1].replace(",", ""))
            except ValueError:
                amount = 0.0
        status = "confirmed"
        if re.search(r"cancel", blob, re.I):
            status = "cancelled"
        seen.add(booking_id)
        rows.append(
            {
                "bookingid": booking_id,
                "guestname": guest or "Guest",
                "checkin": check_in,
                "checkout": check_out,
                "bookingstatus": status,
                "totalrate": amount,
                "bookingsource": "asia_tech",
                "provider": "asia_tech_cm",
            }
        )

    if rows:
        return rows

    # Fallback: scan plain text for FDR ids.
    plain = _strip_tags(text)
    for match in re.finditer(r"(FDR\d{8,})", plain, re.I):
        booking_id = match.group(1).upper()
        if booking_id in seen:
            continue
        window = plain[max(0, match.start() - 120) : match.end() + 220]
        dates = re.findall(
            r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}-\d{2}-\d{2})",
            window,
        )
        guest = ""
        for part in re.split(r"[\n\t|]+", window):
            part = part.strip()
            if not part or booking_id.lower() in part.lower():
                continue
            if re.search(r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\d{4}-\d{2}-\d{2}", part):
                continue
            if len(part) >= 3:
                guest = part
                break
        seen.add(booking_id)
        rows.append(
            {
                "bookingid": booking_id,
                "guestname": guest or "Guest",
                "checkin": _parse_report_date(dates[0]) if dates else "",
                "checkout": _parse_report_date(dates[1]) if len(dates) > 1 else "",
                "bookingstatus": "confirmed",
                "totalrate": 0,
                "bookingsource": "asia_tech",
                "provider": "asia_tech_cm",
            }
        )
    return rows


class AsiaTechCMClient:
    """Session-backed Channel Manager Booking Report reader."""

    def __init__(self, *, base_url: str = CM_ADMIN_BASE) -> None:
        self.base_url = str(base_url or CM_ADMIN_BASE).rstrip("/") + "/"
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
        )
        self.regid = ""
        self.bs1_id = ""
        self.logged_in = False

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def login(self, email: str, password: str) -> Tuple[bool, str]:
        email = str(email or "").strip()
        password = str(password or "").strip()
        if not email or not password:
            return False, "Channel Manager email and password are required."
        try:
            page = self.session.get(self._url(CM_LOGIN_PATH), timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException as exc:
            return False, f"Cannot reach Asia Tech login: {exc}"[:240]
        token_match = re.search(
            r'id=["\']form_token["\'][^>]*value=["\']([^"\']+)',
            page.text,
            re.I,
        )
        if not token_match:
            token_match = re.search(
                r'value=["\']([^"\']+)["\'][^>]*id=["\']form_token["\']',
                page.text,
                re.I,
            )
        token = token_match.group(1) if token_match else ""
        data = {
            "form_token": token,
            "login_email": email,
            "login_password": password,
            "login_type": "0",
        }
        try:
            resp = self.session.post(
                self._url(CM_LOGIN_AJAX),
                data=data,
                timeout=REQUEST_TIMEOUT_S,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._url(CM_LOGIN_PATH),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        except requests.RequestException as exc:
            return False, f"Asia Tech login failed: {exc}"[:240]
        body = (resp.text or "").strip()
        if body in ("1", "2"):
            self.logged_in = True
            return True, ""
        plain = _strip_tags(body) or body
        return False, plain[:240] or "Asia Tech Channel Manager login failed."

    def _load_report_ids(self) -> None:
        try:
            page = self.session.get(self._url(CM_REPORT_PAGE), timeout=REQUEST_TIMEOUT_S)
        except requests.RequestException:
            return
        reg = re.search(
            r'id=["\']regid["\'][^>]*value=["\']([^"\']*)',
            page.text,
            re.I,
        )
        if not reg:
            reg = re.search(
                r'value=["\']([^"\']*)["\'][^>]*id=["\']regid["\']',
                page.text,
                re.I,
            )
        bs1 = re.search(
            r'id=["\']bs1_id["\'][^>]*value=["\']([^"\']*)',
            page.text,
            re.I,
        )
        if not bs1:
            bs1 = re.search(
                r'value=["\']([^"\']*)["\'][^>]*id=["\']bs1_id["\']',
                page.text,
                re.I,
            )
        self.regid = reg.group(1) if reg else self.regid
        self.bs1_id = bs1.group(1) if bs1 else self.bs1_id

    def fetch_report(
        self,
        *,
        booking_type: str,
        querydate: str,
        page: int = 1,
    ) -> Tuple[List[Dict[str, Any]], str]:
        if not self.logged_in:
            return [], "Not logged in to Asia Tech Channel Manager."
        if not self.regid and not self.bs1_id:
            self._load_report_ids()
        booking_type = str(booking_type or "checkin").strip().lower()
        querydate = str(querydate or "").strip()
        data = {
            "breport_regid": self.regid,
            "breport_bs1_id": self.bs1_id,
            "booking_type": booking_type,
            "querydate": querydate,
        }
        if page and page > 1:
            data["page"] = str(page)
        try:
            resp = self.session.post(
                self._url(CM_REPORT_AJAX),
                data=data,
                timeout=REQUEST_TIMEOUT_S,
                headers={
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": self._url(CM_REPORT_PAGE),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
        except requests.RequestException as exc:
            return [], f"Booking report request failed: {exc}"[:240]
        html = resp.text or ""
        if "window.location.assign('login')" in html or "Sign in" in html:
            self.logged_in = False
            return [], "Asia Tech Channel Manager session expired."
        rows = parse_booking_report_html(html)
        # Follow simple pagination if present.
        if page <= 1:
            pages = {
                int(p)
                for p in re.findall(r'data-page=["\'](\d+)["\']', html, re.I)
                if str(p).isdigit()
            }
            for next_page in sorted(pages):
                if next_page <= 1:
                    continue
                more, err = self.fetch_report(
                    booking_type=booking_type,
                    querydate=querydate,
                    page=next_page,
                )
                if err:
                    break
                rows.extend(more)
        return rows, ""


def fetch_checkin_booking_reports(
    *,
    email: str,
    password: str,
    days: Optional[List[date]] = None,
    booking_types: Optional[List[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Login and pull CM Booking Report rows by check-in (and related) dates."""
    meta: Dict[str, Any] = {
        "cm_ok": False,
        "cm_error": "",
        "cm_days": 0,
        "cm_pulled": 0,
        "cm_types": [],
    }
    client = AsiaTechCMClient()
    ok, err = client.login(email, password)
    if not ok:
        meta["cm_error"] = err
        return [], meta
    meta["cm_ok"] = True
    types = booking_types or ["checkin", "checkout", "booking"]
    meta["cm_types"] = list(types)
    day_list = days or checkin_report_dates()
    meta["cm_days"] = len(day_list)
    by_id: Dict[str, Dict[str, Any]] = {}
    errors: List[str] = []
    for day in day_list:
        qdate = format_querydate(day)
        for btype in types:
            # Check-in dates only need checkin type; still try checkout for today-ish.
            if btype == "checkout" and day not in (
                date.today(),
                date.today() - timedelta(days=1),
            ):
                continue
            if btype == "booking" and day != date.today():
                continue
            rows, row_err = client.fetch_report(booking_type=btype, querydate=qdate)
            if row_err:
                errors.append(f"{btype}@{qdate}: {row_err}")
                if "session expired" in row_err.lower() or "not logged in" in row_err.lower():
                    meta["cm_error"] = row_err
                    return list(by_id.values()), meta
                continue
            for row in rows:
                bid = str(row.get("bookingid") or "").strip().upper()
                if not bid:
                    continue
                # Prefer rows that include stay dates.
                prev = by_id.get(bid)
                if not prev or (row.get("checkin") and not prev.get("checkin")):
                    by_id[bid] = row
                elif row.get("checkin") and prev.get("checkin"):
                    by_id[bid] = row
    meta["cm_pulled"] = len(by_id)
    if errors and not by_id:
        meta["cm_error"] = errors[0][:240]
    elif errors:
        meta["cm_error"] = ""
    return list(by_id.values()), meta
