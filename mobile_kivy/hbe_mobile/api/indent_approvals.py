"""Stores Indent Approval — list pending/recent + approve/reject via form POST."""

from __future__ import annotations

from typing import Any

from hbe_mobile.api.client import ApiClient, ApiError


def list_indents(client: ApiClient, *, view: str = "pending") -> dict[str, Any]:
    """Prefer JSON API; fall back to empty on older servers."""
    params = {"view": "recent" if view in ("recent", "approved", "history") else "pending"}
    try:
        data = client.get_json("/stores/api/indent-approvals", params=params)
    except ApiError:
        raise
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Failed to load indents"))
    return data


def decide_indent(
    client: ApiClient,
    *,
    indent_id: int,
    decision: str,
    outlet: str = "",
    decision_note: str = "",
) -> None:
    decision_l = (decision or "").strip().lower()
    if decision_l not in {"approved", "rejected"}:
        raise ApiError("Choose approve or reject.")
    if decision_l == "rejected" and not (decision_note or "").strip():
        raise ApiError("Add a short reason when rejecting.")
    form = {
        "outlet": outlet or "bar",
        "decision": decision_l,
        "decision_note": (decision_note or "").strip(),
    }
    response = client.request(
        "POST",
        f"/stores/indent/{int(indent_id)}/decide",
        data=form,
        follow_redirects=True,
    )
    text = (response.text or "").lower()
    if response.status_code >= 400:
        raise ApiError(f"Decision failed ({response.status_code})")
    if "choose approve or reject" in text:
        raise ApiError("Choose approve or reject.")
    if "add a short reason" in text:
        raise ApiError("Add a short reason when rejecting.")
    if "not waiting for approval" in text:
        raise ApiError("This indent is not waiting for approval.")
