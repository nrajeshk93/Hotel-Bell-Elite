"""Outbound email helpers (SMTP)."""

from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger(__name__)

_ROOT = Path(__file__).resolve().parent
_OUTBOX_PATH = _ROOT / "logs" / "mail_outbox.log"


def smtp_configured() -> bool:
    host = (os.environ.get("SMTP_HOST") or "").strip()
    password = (os.environ.get("SMTP_PASSWORD") or "").strip()
    return bool(host and password)


def _is_local_request_host(host: str) -> bool:
    h = (host or "").split(":")[0].strip().lower()
    if not h:
        return False
    if h in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
        return True
    if h.startswith("192.168.") or h.startswith("10."):
        return True
    # Common RFC1918 172.16.0.0 – 172.31.255.255
    if h.startswith("172."):
        try:
            second = int(h.split(".")[1])
            return 16 <= second <= 31
        except (IndexError, ValueError):
            return False
    return False


def app_base_url(request=None) -> str:
    """
    Public origin for links in emails.

    Prefer the live request host when the browser hit a local/dev server so the
    unlock token (stored in that server's DB) is opened against the same app.
    Use APP_BASE_URL for production / reverse-proxy deployments.
    """
    configured = (os.environ.get("APP_BASE_URL") or "").strip().rstrip("/")
    if request is not None:
        current = (request.url_root or "").rstrip("/")
        if current and _is_local_request_host(request.host or ""):
            return current
        if configured:
            return configured
        return current
    return configured


def append_mail_outbox(*, kind: str, to_addr: str, subject: str, body: str) -> None:
    """Always record outbound mail locally so unlock links are recoverable without SMTP."""
    try:
        _OUTBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with _OUTBOX_PATH.open("a", encoding="utf-8") as fh:
            fh.write(
                f"\n===== {stamp} | {kind} =====\n"
                f"To: {to_addr}\n"
                f"Subject: {subject}\n"
                f"{body.strip()}\n"
            )
    except OSError:
        logger.exception("Failed to write mail outbox")


def send_email(*, to_addr: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    """
    Send an email via SMTP env config.
    Returns True on success, False if SMTP is unset or send fails.
    """
    to_addr = (to_addr or "").strip()
    if not to_addr:
        logger.warning("send_email skipped: empty recipient")
        return False

    append_mail_outbox(
        kind="email",
        to_addr=to_addr,
        subject=subject,
        body=text_body or "",
    )

    host = (os.environ.get("SMTP_HOST") or "").strip()
    if not host:
        logger.warning("send_email skipped: SMTP_HOST is not configured")
        return False

    port = int((os.environ.get("SMTP_PORT") or "587").strip() or "587")
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = os.environ.get("SMTP_PASSWORD") or ""
    from_addr = (os.environ.get("SMTP_FROM") or user or "noreply@localhost").strip()
    use_tls = (os.environ.get("SMTP_USE_TLS") or "1").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg.set_content(text_body or "")
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    try:
        if use_tls:
            context = ssl.create_default_context()
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                smtp.ehlo()
                smtp.starttls(context=context)
                smtp.ehlo()
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.send_message(msg)
        return True
    except Exception:
        logger.exception("Failed to send email to %s", to_addr)
        return False


def send_account_unlock_email(*, to_addr: str, username: str, unlock_url: str) -> bool:
    subject = "Unlock your Hotel Bell Elite account"
    text_body = (
        f"Hello {username},\n\n"
        "Your account was locked after too many failed sign-in attempts.\n"
        "Open the link below to unlock your account (valid for 1 hour):\n\n"
        f"{unlock_url}\n\n"
        "If you did not try to sign in, contact your administrator.\n"
    )
    safe_user = html.escape(username or "")
    safe_url = html.escape(unlock_url or "", quote=True)
    html_body = (
        f"<p>Hello <strong>{safe_user}</strong>,</p>"
        "<p>Your account was locked after too many failed sign-in attempts.</p>"
        f'<p><a href="{safe_url}">Unlock your account</a> '
        "(link valid for 1 hour).</p>"
        "<p>If you did not try to sign in, contact your administrator.</p>"
    )
    return send_email(
        to_addr=to_addr,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
    )
