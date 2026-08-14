"""Shared helpers for embed-only and soft-nav page fragments."""

from flask import request


def is_embed_request() -> bool:
    """True when the client wants shell-free content (Masters modal inject).

    Full browser navigations to ?embed=1 must still get a complete HTML page
    (CSS/JS). Those use Sec-Fetch-Dest: document / Mode: navigate. Modal
    injects use fetch (Dest: empty, Mode: cors).
    """
    if request.args.get("embed") != "1":
        return False
    dest = (request.headers.get("Sec-Fetch-Dest") or "").strip().lower()
    if dest == "document":
        return False
    mode = (request.headers.get("Sec-Fetch-Mode") or "").strip().lower()
    if mode == "navigate":
        return False
    return True


def is_partial_main_request() -> bool:
    """True when soft-nav wants only .de-main-wrapper (no sidebar chrome)."""
    if request.args.get("partial") == "main":
        return True
    return (request.headers.get("X-De-Partial") or "").strip().lower() == "main"


def is_background_fetch_request() -> bool:
    """True for fetch()/XHR, not a top-level document navigation.

    Soft-nav prefetch of /logout must not clear the session — that left the
    home avatar looking signed in as Administrator until the next refresh.
    """
    if is_partial_main_request():
        return True
    if (request.headers.get("X-Requested-With") or "").strip() == "XMLHttpRequest":
        return True
    dest = (request.headers.get("Sec-Fetch-Dest") or "").strip().lower()
    if dest in {"empty", "cors"}:
        return True
    mode = (request.headers.get("Sec-Fetch-Mode") or "").strip().lower()
    return mode == "cors"
