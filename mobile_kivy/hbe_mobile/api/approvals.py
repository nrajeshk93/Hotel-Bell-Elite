"""Accounts Approvals (purchase-verification) — HTML list embeds + JSON mutations."""

from __future__ import annotations

from typing import Any, Optional

from hbe_mobile.api.client import (
    ApiClient,
    ApiError,
    extract_script_json,
    parse_history_rows,
)
from hbe_mobile.models import OutstandingExpense, VerificationEntry


def fetch_outstanding(client: ApiClient) -> list[OutstandingExpense]:
    # All pending (override web FY default with a wide open date range).
    html = client.get_text(
        "/accounts/purchase-verification",
        params={"date_from": "2000-01-01", "date_to": "2099-12-31"},
    )
    data = extract_script_json(html, "cp-outstanding-data")
    if data is None:
        return []
    if not isinstance(data, list):
        return []
    return [OutstandingExpense.from_api(row) for row in data if isinstance(row, dict)]


def fetch_history(client: ApiClient) -> list[VerificationEntry]:
    html = client.get_text(
        "/accounts/purchase-verification",
        params={"view": "history", "payment_date_from": "2000-01-01", "payment_date_to": "2099-12-31"},
    )
    rows = parse_history_rows(html)
    return [VerificationEntry.from_history_row(r) for r in rows]


def create_verification(
    client: ApiClient,
    *,
    supplier_id: int,
    allocations: list[dict[str, Any]],
    notes: str = "",
    company: str = "",
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "supplier_id": supplier_id,
        "allocations": allocations,
        "notes": notes,
    }
    if company:
        body["company"] = company
    data = client.post_json("/accounts/purchase-verification/create", body)
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(
            str((data or {}).get("error") if isinstance(data, dict) else "Verify failed"),
            payload=data,
        )
    return data


def delete_verification(client: ApiClient, payment_id: int) -> None:
    data = client.post_json(
        "/accounts/purchase-verification/delete",
        {"payment_id": int(payment_id)},
    )
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(
            str((data or {}).get("error") if isinstance(data, dict) else "Revert failed"),
            payload=data,
        )


def verification_detail(client: ApiClient, verification_id: int) -> Optional[dict[str, Any]]:
    data = client.get_json(f"/accounts/purchase-verification/{int(verification_id)}")
    if not isinstance(data, dict) or not data.get("ok"):
        return None
    return data.get("payment")


def fetch_expense_detail(client: ApiClient, expense_id: int) -> dict[str, Any]:
    data = client.get_json(f"/accounts/purchase-verification/expense/{int(expense_id)}")
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(
            str((data or {}).get("error") if isinstance(data, dict) else "Expense detail failed"),
            payload=data,
        )
    return data
