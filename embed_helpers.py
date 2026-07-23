"""Shared helpers for embed-only and soft-nav page fragments."""

from flask import request


def is_embed_request() -> bool:
    """True when the client wants shell-free content (Masters modal inject)."""
    return request.args.get("embed") == "1"


def is_partial_main_request() -> bool:
    """True when soft-nav wants only .de-main-wrapper (no sidebar chrome)."""
    if request.args.get("partial") == "main":
        return True
    return (request.headers.get("X-De-Partial") or "").strip().lower() == "main"
