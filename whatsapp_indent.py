"""Send indent approval WhatsApp interactive messages when an indent awaits approval."""

from __future__ import annotations

import logging
import os
import uuid

import whatsapp_client as wa
from indent_approval_pdf import format_indent_total_amount

log = logging.getLogger(__name__)

# Hard default: at most 10 successful indent-approval WhatsApp sends per rolling 24 hours.
_DEFAULT_DAILY_CAP = 10


def indent_approver_numbers() -> list[str]:
    return wa.parse_whatsapp_recipients(
        os.environ.get("WHATSAPP_INDENT_APPROVER_NUMBERS") or ""
    )


def indent_approver_name() -> str:
    return (os.environ.get("WHATSAPP_INDENT_APPROVER_NAME") or "Neeraj").strip() or "Neeraj"


def indent_whatsapp_daily_cap() -> int:
    """Max successful indent-approval WhatsApp sends allowed in a rolling 24-hour window."""
    raw = (os.environ.get("WHATSAPP_INDENT_DAILY_CAP") or str(_DEFAULT_DAILY_CAP)).strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return _DEFAULT_DAILY_CAP


def count_todays_indent_whatsapp_sends(conn) -> int:
    """Successful approval sends in the last 24 hours (local), including later-superseded ones."""
    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM store_indent_whatsapp_messages
        WHERE status IN ('sent', 'superseded')
          AND datetime(created_at) >= datetime('now', 'localtime', '-24 hours')
        """
    ).fetchone()
    return int(row["c"] if row and row["c"] is not None else 0)


def remaining_indent_whatsapp_daily_quota(conn) -> int:
    cap = indent_whatsapp_daily_cap()
    used = count_todays_indent_whatsapp_sends(conn)
    return max(0, cap - used)


def allocate_approval_token(conn) -> str:
    """Return a unique UUID4 approval token (retries on the rare collision)."""
    for _ in range(12):
        token = str(uuid.uuid4())
        row = conn.execute(
            "SELECT 1 FROM store_indents WHERE approval_token = ? LIMIT 1",
            (token,),
        ).fetchone()
        if not row:
            return token
    raise RuntimeError("Could not allocate a unique indent approval token.")


def approve_button_id(token: str) -> str:
    return f"approve_{(token or '').strip()}"


def reject_button_id(token: str) -> str:
    return f"reject_{(token or '').strip()}"


def assign_fresh_approval_token(conn, indent_id: int) -> str:
    """Assign a new Approval Token for a pending/submit round. Clears prior WA audit fields."""
    token = allocate_approval_token(conn)
    conn.execute(
        """
        UPDATE store_indents
        SET approval_token = ?,
            wa_decided_by = '',
            wa_decision_message_id = '',
            wa_template_message_id = '',
            wa_interactive_message_id = ''
        WHERE id = ?
        """,
        (token, indent_id),
    )
    log.info(
        "Approval Token Generated indent_id=%s token=%s",
        indent_id,
        token,
    )
    return token


def ensure_indent_approval_token(conn, indent_id: int) -> str:
    """Return existing token or allocate one if missing (e.g. legacy pending rows)."""
    row = conn.execute(
        "SELECT approval_token FROM store_indents WHERE id = ?",
        (indent_id,),
    ).fetchone()
    if not row:
        return ""
    token = (row["approval_token"] or "").strip()
    if token:
        return token
    return assign_fresh_approval_token(conn, indent_id)


SEND_KIND_INTERACTIVE = "interactive"

# Hard ceiling for one approval_token: each approver gets exactly 1 interactive message.
_SENDS_PER_APPROVER_PER_ROUND = 1

INTERACTIVE_TEMPLATE_NAME = "interactive_approve_reject"


def _record_send(
    conn,
    *,
    indent_id: int,
    recipient_phone: str,
    wa_message_id: str,
    template_name: str,
    status: str,
    error_message: str = "",
    approval_token: str = "",
    send_kind: str = "",
) -> int:
    cur = conn.execute(
        """
        INSERT INTO store_indent_whatsapp_messages
            (indent_id, recipient_phone, wa_message_id, template_name, status,
             error_message, approval_token, send_kind)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            indent_id,
            recipient_phone,
            wa_message_id or "",
            template_name,
            status,
            (error_message or "")[:500],
            (approval_token or "").strip(),
            (send_kind or "").strip(),
        ),
    )
    return int(cur.lastrowid or 0)


def _already_sent_approval(
    conn,
    *,
    indent_id: int,
    recipient_phone: str,
    approval_token: str = "",
) -> bool:
    """True if this indent+approver already claimed/sent interactive for the current token round."""
    phone = (recipient_phone or "").strip()
    if not phone:
        return False
    token = (approval_token or "").strip()
    if token:
        row = conn.execute(
            """
            SELECT 1
            FROM store_indent_whatsapp_messages
            WHERE indent_id = ?
              AND recipient_phone = ?
              AND approval_token = ?
              AND send_kind = ?
              AND status IN ('sending', 'sent', 'failed')
            LIMIT 1
            """,
            (indent_id, phone, token, SEND_KIND_INTERACTIVE),
        ).fetchone()
        if row:
            return True
    row = conn.execute(
        """
        SELECT 1
        FROM store_indent_whatsapp_messages
        WHERE indent_id = ?
          AND recipient_phone = ?
          AND status IN ('sending', 'sent', 'failed')
          AND COALESCE(send_kind, '') = ?
        LIMIT 1
        """,
        (indent_id, phone, SEND_KIND_INTERACTIVE),
    ).fetchone()
    return row is not None


def _count_round_sends(conn, *, indent_id: int, approval_token: str) -> int:
    token = (approval_token or "").strip()
    if not token:
        return 0
    row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM store_indent_whatsapp_messages
        WHERE indent_id = ?
          AND approval_token = ?
          AND status IN ('sending', 'sent', 'failed')
        """,
        (indent_id, token),
    ).fetchone()
    return int(row["c"] if row and row["c"] is not None else 0)


def _claim_send(
    conn,
    *,
    indent_id: int,
    recipient_phone: str,
    approval_token: str,
    send_kind: str,
    template_name: str,
) -> int | None:
    """Atomically claim one outbound slot. Returns row id or None if already claimed/sent.

    Commits immediately so concurrent notifiers see the claim before any Meta HTTP call.
    """
    phone = (recipient_phone or "").strip()
    token = (approval_token or "").strip()
    kind = (send_kind or "").strip()
    if not phone or not token or not kind:
        return None
    try:
        row_id = _record_send(
            conn,
            indent_id=indent_id,
            recipient_phone=phone,
            wa_message_id="",
            template_name=template_name,
            status="sending",
            approval_token=token,
            send_kind=kind,
        )
        conn.commit()
        return row_id
    except Exception as exc:
        # Unique claim index conflict → another worker already owns this send.
        try:
            conn.rollback()
        except Exception:
            pass
        log.info(
            "WhatsApp indent send skipped as duplicate indent_id=%s to=%s token=%s kind=%s (%s)",
            indent_id,
            phone,
            token[:8],
            kind,
            type(exc).__name__,
        )
        return None


def _finalize_send(
    conn,
    row_id: int,
    *,
    status: str,
    wa_message_id: str = "",
    error_message: str = "",
) -> None:
    if not row_id:
        return
    conn.execute(
        """
        UPDATE store_indent_whatsapp_messages
        SET status = ?,
            wa_message_id = COALESCE(NULLIF(?, ''), wa_message_id),
            error_message = ?
        WHERE id = ?
        """,
        (status, wa_message_id or "", (error_message or "")[:500], row_id),
    )


def _store_indent_outbound_message_id(conn, indent_id: int, *, interactive_message_id: str) -> None:
    """Keep latest outbound WhatsApp interactive id on the indent."""
    btn = (interactive_message_id or "").strip()
    if not indent_id or not btn:
        return
    conn.execute(
        """
        UPDATE store_indents
        SET wa_interactive_message_id = ?
        WHERE id = ?
        """,
        (btn, indent_id),
    )


def _acquire_notify_lock(conn, indent_id: int) -> bool:
    """Single-flight lock per indent. Stale locks older than 2 minutes are stealable."""
    cur = conn.execute(
        """
        UPDATE store_indents
        SET wa_notify_lock = 1,
            wa_notify_lock_at = datetime('now', 'localtime')
        WHERE id = ?
          AND status = 'pending'
          AND (
            COALESCE(wa_notify_lock, 0) = 0
            OR COALESCE(wa_notify_lock_at, '') = ''
            OR datetime(wa_notify_lock_at) < datetime('now', 'localtime', '-2 minutes')
          )
        """,
        (indent_id,),
    )
    if cur.rowcount > 0:
        conn.commit()
        return True
    log.info(
        "WhatsApp indent notify skipped — single-flight lock held indent_id=%s",
        indent_id,
    )
    return False


def _release_notify_lock(conn, indent_id: int) -> None:
    conn.execute(
        """
        UPDATE store_indents
        SET wa_notify_lock = 0,
            wa_notify_lock_at = ''
        WHERE id = ?
        """,
        (indent_id,),
    )


def supersede_indent_whatsapp_sends(conn, indent_id: int) -> None:
    """Mark prior successful/in-flight/failed sends as superseded so a new approval round can notify again."""
    conn.execute(
        """
        UPDATE store_indent_whatsapp_messages
        SET status = 'superseded'
        WHERE indent_id = ?
          AND status IN ('sent', 'sending', 'failed')
        """,
        (indent_id,),
    )
    _release_notify_lock(conn, indent_id)


def _approval_body_text(*, indent_no: str, total_amount: str, approver_name: str) -> str:
    """Body for the single interactive message — never includes the approval token."""
    name = (approver_name or "").strip() or "Approver"
    return (
        f"Hi {name},\n"
        f"Indent ID: {indent_no}\n"
        f"Estimated Total: {total_amount}\n"
        f"Please Approve or Reject this indent."
    )


def notify_indent_pending_whatsapp(
    conn,
    indent_id: int,
    *,
    outlet_label: str = "",
    force: bool = False,
) -> tuple[bool, str]:
    """Send exactly one interactive Approve/Reject WhatsApp message per approver.

    Body includes indent id, estimated total, and approval copy. The Approval Token
    is embedded only in button ids (``approve_<token>`` / ``reject_<token>``) and
    must never appear in the message body.

    Meta constraint: interactive reply buttons are allowed inside an open 24-hour
    customer-care window. Outside that window Meta may reject free-form interactive
    sends (templates are required for cold outreach). Template quick-reply payloads
    cannot carry a per-indent UUID the way interactive ``reply.id`` can, so this
    path intentionally sends **one interactive message only** — never a
    template-then-interactive pair. If Meta blocks the send, the API error is
    returned; there is no dual-message fallback.

    Idempotent per indent+approver+approval_token for the current approval round:
    claim-before-send (status ``sending``) is committed before any Meta HTTP call
    so concurrent notifiers cannot double-spend. Callers starting a new round
    (e.g. reject → resubmit) should call ``supersede_indent_whatsapp_sends`` first.

    Enforces:
    - single-flight lock per indent
    - per-approval_token burst cap (N approvers × 1 message)
    - rolling 24-hour send cap (default 10; ``WHATSAPP_INDENT_DAILY_CAP``)

    Returns (ok, message). Caller owns commit. Failures do not raise.
    """
    if not wa.whatsapp_configured():
        return False, "WhatsApp is not configured."
    # Live Meta HTTP is gated inside whatsapp_client.send_payload
    # (TESTING / WHATSAPP_DRY_RUN). Mocks in unit tests still exercise this path.

    recipients = indent_approver_numbers()
    if not recipients:
        return False, "No WhatsApp indent approver numbers configured."

    indent = conn.execute(
        """
        SELECT i.*, u.full_name AS created_by_name
        FROM store_indents i
        LEFT JOIN users u ON u.id = i.created_by
        WHERE i.id = ?
        """,
        (indent_id,),
    ).fetchone()
    if not indent:
        return False, "Indent not found."
    if (indent["status"] or "") != "pending":
        return False, "Indent is not waiting for approval."

    approval_token = ensure_indent_approval_token(conn, indent_id)
    if not approval_token:
        return False, "Could not allocate approval token."

    if not _acquire_notify_lock(conn, indent_id):
        return True, "WhatsApp approval notify already in progress."

    try:
        return _notify_indent_pending_whatsapp_locked(
            conn,
            indent_id,
            indent=indent,
            recipients=recipients,
            approval_token=approval_token,
            outlet_label=outlet_label,
            force=force,
        )
    finally:
        try:
            _release_notify_lock(conn, indent_id)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass


def _notify_indent_pending_whatsapp_locked(
    conn,
    indent_id: int,
    *,
    indent,
    recipients: list[str],
    approval_token: str,
    outlet_label: str,
    force: bool,
) -> tuple[bool, str]:
    del outlet_label  # reserved for future body copy; PDF path removed
    if not force:
        filtered = []
        for phone in recipients:
            if _already_sent_approval(
                conn,
                indent_id=indent_id,
                recipient_phone=phone,
                approval_token=approval_token,
            ):
                log.info(
                    "WhatsApp indent send skipped as duplicate indent_id=%s to=%s token=%s",
                    indent_id,
                    phone,
                    approval_token[:8],
                )
                continue
            filtered.append(phone)
        recipients = filtered
    if not recipients:
        return True, "WhatsApp approval request already sent."

    round_budget = len(indent_approver_numbers()) * _SENDS_PER_APPROVER_PER_ROUND
    already = _count_round_sends(conn, indent_id=indent_id, approval_token=approval_token)
    if already >= round_budget:
        log.warning(
            "WhatsApp indent notify blocked by per-token burst cap indent_id=%s "
            "token=%s used=%s cap=%s",
            indent_id,
            approval_token[:8],
            already,
            round_budget,
        )
        return True, "WhatsApp approval request already sent for this approval round."

    remaining = remaining_indent_whatsapp_daily_quota(conn)
    cap = indent_whatsapp_daily_cap()
    if remaining <= 0:
        log.warning(
            "WhatsApp indent approval blocked by daily cap indent_id=%s used=%s cap=%s",
            indent_id,
            count_todays_indent_whatsapp_sends(conn),
            cap,
        )
        return (
            False,
            f"WhatsApp indent approval limit reached ({cap} messages / 24 hours). "
            "More indents can still be created; WhatsApp notify resumes after the window resets "
            "or raise WHATSAPP_INDENT_DAILY_CAP.",
        )
    if len(recipients) > remaining:
        recipients = recipients[:remaining]
        log.warning(
            "WhatsApp indent approval truncated to remaining daily quota indent_id=%s remaining=%s",
            indent_id,
            remaining,
        )

    lines = [
        dict(row)
        for row in conn.execute(
            """
            SELECT item_name, quantity, unit, notes, approximate_price
            FROM store_indent_lines
            WHERE indent_id = ?
            ORDER BY id
            """,
            (indent_id,),
        ).fetchall()
    ]
    if not lines:
        return False, "Indent has no items."

    indent_data = dict(indent)
    indent_no = indent_data.get("indent_no") or f"IND-{indent_id}"
    total_amount = format_indent_total_amount(lines)
    body_text = _approval_body_text(
        indent_no=str(indent_no),
        total_amount=total_amount,
        approver_name=indent_approver_name(),
    )
    if approval_token in body_text or approval_token[:8] in body_text:
        # Defensive: token must never appear in the visible body.
        body_text = (
            f"Indent ID: {indent_no}\n"
            f"Estimated Total: {total_amount}\n"
            f"Please Approve or Reject this indent."
        )

    approve_id = approve_button_id(approval_token)
    reject_id = reject_button_id(approval_token)

    sent = 0
    failed = 0
    last_error = ""

    for phone in recipients:
        if (
            _count_round_sends(conn, indent_id=indent_id, approval_token=approval_token)
            >= round_budget
        ):
            log.warning(
                "WhatsApp indent notify hit per-token burst mid-loop indent_id=%s token=%s",
                indent_id,
                approval_token[:8],
            )
            break

        claim_id = _claim_send(
            conn,
            indent_id=indent_id,
            recipient_phone=phone,
            approval_token=approval_token,
            send_kind=SEND_KIND_INTERACTIVE,
            template_name=INTERACTIVE_TEMPLATE_NAME,
        )
        if claim_id is None:
            continue

        ok_btn, btn_err, btn_body = wa.send_interactive_buttons(
            phone,
            body_text,
            [
                (approve_id, "Approve"),
                (reject_id, "Reject"),
            ],
        )
        if ok_btn:
            button_wa_id = wa.first_message_id(btn_body)
            _finalize_send(
                conn,
                claim_id,
                status="sent",
                wa_message_id=button_wa_id,
            )
            if button_wa_id:
                _store_indent_outbound_message_id(
                    conn,
                    indent_id,
                    interactive_message_id=button_wa_id,
                )
            else:
                log.warning(
                    "WhatsApp interactive send missing message id indent_id=%s to=%s",
                    indent_id,
                    phone,
                )
            conn.commit()
            log.info(
                "Interactive Message Sent indent_id=%s token=%s approve_id=%s reject_id=%s "
                "to=%s WhatsApp Message ID=%s",
                indent_id,
                approval_token,
                approve_id,
                reject_id,
                phone,
                button_wa_id,
            )
            sent += 1
        else:
            failed += 1
            last_error = btn_err or "interactive send failed"
            _finalize_send(
                conn,
                claim_id,
                status="failed",
                error_message=last_error,
            )
            conn.commit()
            log.warning(
                "WhatsApp indent approval interactive failed indent_id=%s to=%s err=%s",
                indent_id,
                phone,
                last_error,
            )

    if sent and not failed:
        return True, f"WhatsApp approval request sent to {sent} recipient(s)."
    if sent and failed:
        return True, f"WhatsApp sent to {sent}; {failed} failed. {last_error}".strip()
    return False, last_error or "WhatsApp approval request failed."
