"""Customer Feedback - shareable links + analytics under Communication Hub."""

from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime

from flask import jsonify, render_template, request, url_for

from db import (
    ensure_customer_feedback_schema,
    get_db,
)
from mailer import app_base_url

log = logging.getLogger(__name__)

_pop_auth_notice = None
_get_user = None

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_SOURCES = frozenset({"manual", "hotel", "restaurant", "bar", "whatsapp"})


def _bind_helpers(*, pop_auth_notice, get_user):
    global _pop_auth_notice, _get_user
    _pop_auth_notice = pop_auth_notice
    _get_user = get_user


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _clamp_rating(value) -> int | None:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return None
    if n < 1 or n > 5:
        return None
    return n


def _public_feedback_url(token: str) -> str:
    base = (app_base_url() or "").rstrip("/")
    path = f"/f/{token}"
    if base:
        return f"{base}{path}"
    try:
        return url_for("customer_feedback_public", token=token, _external=True)
    except Exception:
        return path


def create_feedback_invite(
    conn,
    *,
    customer_name: str = "",
    phone: str = "",
    source: str = "manual",
    outlet: str = "",
    note: str = "",
    user_id=None,
) -> dict:
    ensure_customer_feedback_schema(conn)
    token = secrets.token_urlsafe(18)
    src = (source or "manual").strip().lower()
    if src not in _SOURCES:
        src = "manual"
    name = (customer_name or "").strip()[:200]
    phone_clean = re.sub(r"\D+", "", str(phone or ""))[-15:]
    note_clean = (note or "").strip()[:500]
    outlet_clean = (outlet or "").strip()[:80]
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO customer_feedback_invites
            (token, customer_name, phone_e164, source, outlet, note, status, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?)
        """,
        (token, name, phone_clean, src, outlet_clean, note_clean, user_id, now),
    )
    conn.commit()
    invite_id = int(cur.lastrowid)
    return {
        "id": invite_id,
        "token": token,
        "url": _public_feedback_url(token),
        "customer_name": name,
        "phone": phone_clean,
        "source": src,
        "outlet": outlet_clean,
        "status": "open",
        "created_at": now,
    }


def feedback_summary(conn) -> dict:
    ensure_customer_feedback_schema(conn)
    invite_row = conn.execute(
        "SELECT COUNT(*) AS c FROM customer_feedback_invites"
    ).fetchone()
    response_row = conn.execute(
        "SELECT COUNT(*) AS c, AVG(rating) AS avg_rating FROM customer_feedback_responses"
    ).fetchone()
    month_row = conn.execute(
        """
        SELECT COUNT(*) AS c
        FROM customer_feedback_responses
        WHERE submitted_at >= datetime('now', 'start of month', 'localtime')
        """
    ).fetchone()
    dist = {str(i): 0 for i in range(1, 6)}
    for row in conn.execute(
        """
        SELECT rating, COUNT(*) AS c
        FROM customer_feedback_responses
        GROUP BY rating
        """
    ):
        key = str(int(row["rating"] or 0))
        if key in dist:
            dist[key] = int(row["c"] or 0)

    invites = int(invite_row["c"] or 0) if invite_row else 0
    responses = int(response_row["c"] or 0) if response_row else 0
    avg = response_row["avg_rating"] if response_row else None
    avg_rating = round(float(avg), 2) if avg is not None else None
    rate = round((100.0 * responses / invites), 1) if invites else 0.0
    return {
        "invites": invites,
        "responses": responses,
        "avg_rating": avg_rating,
        "response_rate_pct": rate,
        "responses_this_month": int(month_row["c"] or 0) if month_row else 0,
        "rating_distribution": dist,
    }


def list_feedback_responses(conn, *, limit: int = 50, offset: int = 0) -> list[dict]:
    ensure_customer_feedback_schema(conn)
    limit = max(1, min(200, int(limit or 50)))
    offset = max(0, int(offset or 0))
    rows = conn.execute(
        """
        SELECT
            r.id,
            r.rating,
            r.service_rating,
            r.food_rating,
            r.ambience_rating,
            r.comment,
            r.submitted_at,
            i.customer_name,
            i.phone_e164,
            i.source,
            i.outlet,
            i.token
        FROM customer_feedback_responses r
        JOIN customer_feedback_invites i ON i.id = r.invite_id
        ORDER BY r.submitted_at DESC, r.id DESC
        LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    out = []
    for row in rows:
        out.append(
            {
                "id": int(row["id"]),
                "rating": int(row["rating"] or 0),
                "service_rating": row["service_rating"],
                "food_rating": row["food_rating"],
                "ambience_rating": row["ambience_rating"],
                "comment": row["comment"] or "",
                "submitted_at": row["submitted_at"] or "",
                "customer_name": row["customer_name"] or "",
                "phone": row["phone_e164"] or "",
                "source": row["source"] or "",
                "outlet": row["outlet"] or "",
            }
        )
    return out


def get_invite_by_token(conn, token: str):
    ensure_customer_feedback_schema(conn)
    tok = (token or "").strip()
    if not _TOKEN_RE.match(tok):
        return None
    return conn.execute(
        "SELECT * FROM customer_feedback_invites WHERE token = ?",
        (tok,),
    ).fetchone()


def submit_feedback(
    conn,
    token: str,
    *,
    rating,
    comment: str = "",
    service_rating=None,
    food_rating=None,
    ambience_rating=None,
) -> dict:
    invite = get_invite_by_token(conn, token)
    if not invite:
        raise ValueError("This feedback link is invalid or has expired.")
    if (invite["status"] or "") == "submitted":
        raise ValueError("Feedback was already submitted for this link.")
    overall = _clamp_rating(rating)
    if overall is None:
        raise ValueError("Please choose an overall rating from 1 to 5.")
    svc = _clamp_rating(service_rating) if service_rating not in (None, "") else None
    food = _clamp_rating(food_rating) if food_rating not in (None, "") else None
    amb = _clamp_rating(ambience_rating) if ambience_rating not in (None, "") else None
    note = (comment or "").strip()[:2000]
    now = _now()
    invite_id = int(invite["id"])
    try:
        conn.execute(
            """
            INSERT INTO customer_feedback_responses
                (invite_id, rating, service_rating, food_rating, ambience_rating, comment, submitted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (invite_id, overall, svc, food, amb, note, now),
        )
        conn.execute(
            """
            UPDATE customer_feedback_invites
            SET status = 'submitted', submitted_at = ?
            WHERE id = ?
            """,
            (now, invite_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return {
        "ok": True,
        "rating": overall,
        "submitted_at": now,
        "customer_name": invite["customer_name"] or "",
    }


def register_feedback(app, *, pop_auth_notice, get_user):
    _bind_helpers(pop_auth_notice=pop_auth_notice, get_user=get_user)

    def _page_render(**kwargs):
        kwargs.setdefault("auth_notice", _pop_auth_notice() if _pop_auth_notice else None)
        kwargs.setdefault("de_nav_section", "communication_hub")
        kwargs.setdefault("de_nav_communication_hub_view", "feedback")
        return render_template("communication_hub_feedback.html", **kwargs)

    @app.route("/communication-hub/feedback")
    def communication_hub_feedback():
        user = _get_user() if _get_user else None
        return _page_render(
            page_title="Feedback",
            current_user_name=(
                (user.get("full_name") or user.get("username") or "User").strip()
                if user
                else "User"
            ),
        )

    @app.route("/communication-hub/api/feedback/summary", methods=["GET"])
    def communication_hub_api_feedback_summary():
        conn = get_db()
        try:
            return jsonify({"ok": True, "summary": feedback_summary(conn)})
        finally:
            conn.close()

    @app.route("/communication-hub/api/feedback/responses", methods=["GET"])
    def communication_hub_api_feedback_responses():
        try:
            limit = int(request.args.get("limit") or 50)
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = int(request.args.get("offset") or 0)
        except (TypeError, ValueError):
            offset = 0
        conn = get_db()
        try:
            rows = list_feedback_responses(conn, limit=limit, offset=offset)
            return jsonify({"ok": True, "responses": rows})
        finally:
            conn.close()

    @app.route("/communication-hub/api/feedback/invites", methods=["POST"])
    def communication_hub_api_feedback_invite_create():
        user = _get_user() if _get_user else None
        user_id = user.get("id") if user else None
        data = request.get_json(silent=True) or {}
        if request.form:
            data = {
                "customer_name": request.form.get("customer_name"),
                "phone": request.form.get("phone") or request.form.get("mobile"),
                "source": request.form.get("source"),
                "outlet": request.form.get("outlet"),
                "note": request.form.get("note"),
            }
        conn = get_db()
        try:
            invite = create_feedback_invite(
                conn,
                customer_name=str(data.get("customer_name") or ""),
                phone=str(data.get("phone") or data.get("mobile") or ""),
                source=str(data.get("source") or "manual"),
                outlet=str(data.get("outlet") or ""),
                note=str(data.get("note") or ""),
                user_id=user_id,
            )
            return jsonify({"ok": True, "invite": invite})
        except Exception as exc:
            log.exception("feedback invite create failed")
            return jsonify({"ok": False, "error": str(exc) or "Could not create link."}), 400
        finally:
            conn.close()

    @app.route("/f/<token>", methods=["GET", "POST"])
    def customer_feedback_public(token):
        """Public guest form � no login. Linked from WhatsApp / SMS."""
        conn = get_db()
        try:
            invite = get_invite_by_token(conn, token)
            if not invite:
                return (
                    render_template(
                        "customer_feedback_public.html",
                        error="This feedback link is invalid or has expired.",
                        done=False,
                        invite=None,
                    ),
                    404,
                )
            already = (invite["status"] or "") == "submitted"
            if request.method == "POST":
                if already:
                    return render_template(
                        "customer_feedback_public.html",
                        error="Feedback was already submitted for this link.",
                        done=True,
                        invite=dict(invite),
                    )
                try:
                    submit_feedback(
                        conn,
                        token,
                        rating=request.form.get("rating"),
                        comment=request.form.get("comment") or "",
                        service_rating=request.form.get("service_rating"),
                        food_rating=request.form.get("food_rating"),
                        ambience_rating=request.form.get("ambience_rating"),
                    )
                    return render_template(
                        "customer_feedback_public.html",
                        error=None,
                        done=True,
                        invite=dict(invite),
                        thank_you=True,
                    )
                except ValueError as exc:
                    return render_template(
                        "customer_feedback_public.html",
                        error=str(exc),
                        done=False,
                        invite=dict(invite),
                    )
            return render_template(
                "customer_feedback_public.html",
                error=None,
                done=already,
                invite=dict(invite),
                thank_you=False,
            )
        finally:
            conn.close()
