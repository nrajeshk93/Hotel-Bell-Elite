"""Auth helpers wrapping ApiClient.login / logout."""

from __future__ import annotations

from typing import Any

from hbe_mobile.api.client import ApiClient
from hbe_mobile.models import UserSession


def login(
    client: ApiClient,
    username: str,
    password: str,
    *,
    captcha: str = "",
) -> UserSession:
    result: dict[str, Any] = client.login(username, password, captcha=captcha)
    if result.get("ok"):
        access: dict[str, Any] = {}
        display_name = username
        try:
            session = client.get_json("/api/mobile/session")
            if isinstance(session, dict) and session.get("ok"):
                access = dict(session.get("access") or {})
                display_name = str(
                    session.get("display_name") or session.get("username") or username
                ).strip() or username
        except Exception:
            access = {}
        return UserSession(
            authenticated=True,
            username=username,
            display_name=display_name,
            must_change_password=bool(result.get("must_change_password")),
            access=access,
        )
    return UserSession(
        authenticated=False,
        captcha_required=bool(result.get("captcha_required")),
        error=str(result.get("error") or "Sign-in failed"),
    )
