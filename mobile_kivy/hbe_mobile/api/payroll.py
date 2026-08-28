"""Employee Payroll mobile JSON client helpers."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Optional

from hbe_mobile.api.client import ApiClient, ApiError

_ATT_STATUSES = ("present", "absent", "half_day", "")
_MOBILE_RE = re.compile(r"^\d{10}$")


def period_params(year: Any = None, month: Any = None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if year not in (None, ""):
        params["year"] = int(year)
    if month not in (None, ""):
        params["month"] = int(month)
    return params


def validate_employee_payload(name: str, mobile: str) -> Optional[str]:
    if not (name or "").strip():
        return "Employee Name is required."
    if not _MOBILE_RE.match((mobile or "").strip()):
        return "Mobile number must be exactly 10 digits."
    return None


def validate_attendance_status(status: str) -> Optional[str]:
    if status not in _ATT_STATUSES:
        return "Status must be present, absent, half_day, or empty to clear."
    return None


def validate_credit_payload(employee_id: Any, amount: Any, txn_type: str, payment_type: str = "cash", transaction_id: str = "") -> Optional[str]:
    try:
        emp = int(employee_id or 0)
        raw = abs(float(amount or 0))
    except (TypeError, ValueError):
        return "Valid employee and amount are required."
    if emp <= 0 or raw <= 0:
        return "employee_id, date, and amount greater than 0 are required."
    if txn_type not in ("credit", "repayment"):
        return "transaction_type must be credit or repayment."
    if txn_type == "credit" and (payment_type or "") in ("bank_transfer", "bank") and not (transaction_id or "").strip():
        return "Transaction ID is required for bank transfer advances."
    return None


def validate_tip_payload(employee_id: Any, amount: Any, location: str) -> Optional[str]:
    try:
        emp = int(employee_id or 0)
        raw = float(amount or 0)
    except (TypeError, ValueError):
        return "Please select an employee."
    if emp <= 0:
        return "Please select an employee."
    if raw <= 0:
        return "Please enter a tip amount greater than 0."
    if location not in ("Hotel", "Bar", "Restaurant"):
        return "Tips can only be recorded for Hotel, Bar, or Restaurant."
    return None


def fetch_employees(client: ApiClient, **params: Any) -> dict[str, Any]:
    data = client.get_json("/api/mobile/payroll/employees", params=params or None)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Failed to load employees"))
    return data


def fetch_employee(client: ApiClient, emp_id: int, **params: Any) -> dict[str, Any]:
    data = client.get_json(f"/api/mobile/payroll/employees/{int(emp_id)}", params=params or None)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Employee not found"))
    return data


def create_employee(client: ApiClient, payload: dict[str, Any]) -> dict[str, Any]:
    err = validate_employee_payload(str(payload.get("name") or ""), str(payload.get("mobile") or ""))
    if err:
        raise ApiError(err)
    data = client.post_json("/api/mobile/payroll/employees", payload)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Could not add employee"))
    return data


def fetch_attendance(client: ApiClient, **params: Any) -> dict[str, Any]:
    data = client.get_json("/api/mobile/payroll/attendance", params=params or None)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Failed to load attendance"))
    return data


def mark_attendance(client: ApiClient, employee_id: int, att_date: str, status: str) -> dict[str, Any]:
    err = validate_attendance_status(status)
    if err:
        raise ApiError(err)
    data = client.post_json(
        "/api/mobile/payroll/attendance/mark",
        {"employee_id": int(employee_id), "date": att_date, "status": status},
    )
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Could not mark attendance"))
    return data


def fetch_credits(client: ApiClient, **params: Any) -> dict[str, Any]:
    data = client.get_json("/api/mobile/payroll/credits", params=params or None)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Failed to load credits"))
    return data


def add_credit(client: ApiClient, payload: dict[str, Any]) -> dict[str, Any]:
    err = validate_credit_payload(
        payload.get("employee_id"),
        payload.get("amount"),
        str(payload.get("transaction_type") or "credit"),
        str(payload.get("payment_type") or "cash"),
        str(payload.get("transaction_id") or ""),
    )
    if err:
        raise ApiError(err)
    data = client.post_json("/api/mobile/payroll/credits", payload)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Could not save credit"))
    return data


def fetch_tips(client: ApiClient, **params: Any) -> dict[str, Any]:
    data = client.get_json("/api/mobile/payroll/tips", params=params or None)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Failed to load tips"))
    return data


def add_tip(client: ApiClient, payload: dict[str, Any]) -> dict[str, Any]:
    err = validate_tip_payload(payload.get("employee_id"), payload.get("amount"), str(payload.get("location") or "Hotel"))
    if err:
        raise ApiError(err)
    data = client.post_json("/api/mobile/payroll/tips", payload)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Could not add tip"))
    return data


def fetch_tip_incentive(client: ApiClient, **params: Any) -> dict[str, Any]:
    data = client.get_json("/api/mobile/payroll/tips/incentive", params=params or None)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Failed to load incentive"))
    return data


def today_iso() -> str:
    return date.today().isoformat()
