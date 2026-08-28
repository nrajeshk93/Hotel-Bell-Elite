"""Home notifications API."""

from __future__ import annotations

from hbe_mobile.api.client import ApiClient, ApiError
from hbe_mobile.models import NotificationItem


def fetch_notifications(client: ApiClient) -> list[NotificationItem]:
    data = client.get_json("/home/api/notifications")
    if not isinstance(data, dict) or not data.get("ok"):
        raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Failed"))
    items = data.get("notifications") or []
    return [NotificationItem.from_api(x) for x in items if isinstance(x, dict)]
