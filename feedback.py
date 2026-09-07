"""Customer Feedback - shareable links + analytics under Communication Hub."""

from __future__ import annotations

import sqlite3

import logging
import re
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlparse

from flask import jsonify, redirect, render_template, request, url_for

from db import (
    ensure_customer_feedback_schema,
    get_db,
)
from mailer import app_base_url

log = logging.getLogger(__name__)

_pop_auth_notice = None
_get_user = None

_TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_SOURCES = frozenset({"manual", "hotel", "restaurant", "bar", "whatsapp", "public"})

# Single source of truth for the Google review gate (4–5★).
GOOGLE_REVIEW_URL = (
    "https://search.google.com/local/writereview"
    "?placeid=ChIJSTl7KeOViDARrKxuDpxfEo8"
    "&source=g.page.m.ia._"
    "&laa=nmx-review-solicitation-ia2"
)  # keep & as real ampersands; do not HTML/JSON-escape this constant
GOOGLE_GATE_MIN_RATING = 4


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


_PUBLIC_FEEDBACK_BASE_FALLBACK = "https://belleliteaccounts.com"
INVITE_TTL_HOURS = 24


def _parse_ts(value) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw[:19], fmt)
        except ValueError:
            continue
    return None


def _is_local_share_base(base: str) -> bool:
    raw = (base or "").strip()
    if not raw:
        return True
    try:
        parsed = urlparse(raw if "://" in raw else f"https://{raw}")
        host = (parsed.hostname or "").strip().lower()
    except Exception:
        host = ""
    if not host:
        return True
    if host in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
        return True
    if host.startswith("192.168.") or host.startswith("10."):
        return True
    if host.startswith("172."):
        try:
            second = int(host.split(".")[1])
            return 16 <= second <= 31
        except (IndexError, ValueError):
            return False
    return False


def _feedback_share_base_url() -> str:
    """Production domain for staff share links (never localhost)."""
    base = (app_base_url() or "").strip().rstrip("/")
    if not base or _is_local_share_base(base):
        return _PUBLIC_FEEDBACK_BASE_FALLBACK
    return base


def _public_feedback_url(token: str) -> str:
    base = _feedback_share_base_url().rstrip("/")
    return f"{base}/f/{token}"


def invite_is_expired(invite) -> bool:
    """True when invite expires_at (or created_at+24h) is in the past."""
    if invite is None:
        return True
    try:
        expires_raw = invite["expires_at"]
    except (KeyError, TypeError, IndexError):
        expires_raw = None
    expires_dt = _parse_ts(expires_raw)
    if expires_dt is None:
        try:
            created_raw = invite["created_at"]
        except (KeyError, TypeError, IndexError):
            created_raw = None
        created_dt = _parse_ts(created_raw)
        if created_dt is None:
            return False
        expires_dt = created_dt + timedelta(hours=INVITE_TTL_HOURS)
    return datetime.now() >= expires_dt


def _wants_json() -> bool:
    if request.is_json:
        return True
    accept = (request.headers.get("Accept") or "").lower()
    if "application/json" in accept and "text/html" not in accept.split(",")[0]:
        return True
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return True
    return False


def _request_feedback_payload() -> dict:
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return {
        "rating": request.form.get("rating"),
        "comment": request.form.get("comment") or "",
        "service_rating": request.form.get("service_rating"),
        "food_rating": request.form.get("food_rating"),
        "ambience_rating": request.form.get("ambience_rating"),
    }


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
    expires_at = (datetime.now() + timedelta(hours=INVITE_TTL_HOURS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    params = (
        token,
        name,
        phone_clean,
        src,
        outlet_clean,
        note_clean,
        user_id,
        now,
        expires_at,
    )
    insert_sql = """
        INSERT INTO customer_feedback_invites
            (token, customer_name, phone_e164, source, outlet, note, status,
             created_by, created_at, expires_at)
        VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?)
        """
    try:
        cur = conn.execute(insert_sql, params)
        conn.commit()
    except sqlite3.OperationalError as exc:
        # Production DBs that predate expires_at can miss the column until migrate.
        msg = str(exc).lower()
        if "expires_at" not in msg and "no such column" not in msg:
            raise
        ensure_customer_feedback_schema(conn)
        try:
            conn.commit()
        except Exception:
            pass
        cur = conn.execute(insert_sql, params)
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
        "expires_at": expires_at,
        "expires_in_hours": INVITE_TTL_HOURS,
    }


def get_or_create_public_review_invite(conn) -> dict:
    """QR entry: mint a fresh public invite per visit (stable /review URL)."""
    return create_feedback_invite(conn, source="public", note="qr-review")


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
    if invite_is_expired(invite):
        raise ValueError(
            "This feedback link has expired. Please ask the hotel for a new link."
        )
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
        "google_url": GOOGLE_REVIEW_URL if overall >= GOOGLE_GATE_MIN_RATING else None,
        "redirect_google": overall >= GOOGLE_GATE_MIN_RATING,
    }


def _public_template_kwargs(
    invite=None, *, error=None, done=False, thank_you=False, expired=False
):
    return {
        "error": error,
        "done": done,
        "thank_you": thank_you,
        "expired": expired,
        "invite": invite,
        "google_review_url": GOOGLE_REVIEW_URL,
        "google_gate_min_rating": GOOGLE_GATE_MIN_RATING,
        "hotel_name": "Hotel Bell Elite",
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
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            data = {}
        # Prefer JSON body; only fall back to form when JSON is absent.
        if not data and request.form:
            data = {
                "customer_name": request.form.get("customer_name"),
                "phone": request.form.get("phone") or request.form.get("mobile"),
                "source": request.form.get("source"),
                "outlet": request.form.get("outlet"),
                "note": request.form.get("note"),
            }
        conn = get_db()
        try:
            ensure_customer_feedback_schema(conn)
            try:
                conn.commit()
            except Exception:
                pass
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

    @app.route("/review", methods=["GET"])
    def customer_feedback_review():
        """QR-friendly permanent entry: reuse/create an open public invite, then /f/<token>."""
        conn = get_db()
        try:
            invite = get_or_create_public_review_invite(conn)
            return redirect(url_for("customer_feedback_public", token=invite["token"]))
        finally:
            conn.close()

    @app.route("/f/<token>", methods=["GET", "POST"])
    def customer_feedback_public(token):
        """Public guest form — no login. Linked from WhatsApp / SMS / QR."""
        conn = get_db()
        try:
            invite = get_invite_by_token(conn, token)
            if not invite:
                if _wants_json() and request.method == "POST":
                    return (
                        jsonify(
                            {
                                "ok": False,
                                "error": "This feedback link is invalid or has expired.",
                            }
                        ),
                        404,
                    )
                return (
                    render_template(
                        "customer_feedback_public.html",
                        **_public_template_kwargs(
                            None,
                            error="This feedback link is invalid or has expired.",
                            done=False,
                        ),
                    ),
                    404,
                )
            invite_dict = dict(invite)
            already = (invite["status"] or "") == "submitted"
            expired = invite_is_expired(invite_dict)
            # Expiry wins over already-submitted (friendly expired state).
            if expired:
                expired_msg = (
                    "This feedback link has expired. "
                    "Please ask the hotel for a new link."
                )
                if request.method == "POST":
                    if _wants_json():
                        return (
                            jsonify(
                                {
                                    "ok": False,
                                    "error": expired_msg,
                                    "expired": True,
                                }
                            ),
                            410,
                        )
                return render_template(
                    "customer_feedback_public.html",
                    **_public_template_kwargs(
                        invite_dict,
                        error=None,
                        done=True,
                        expired=True,
                    ),
                )
            if request.method == "POST":
                payload = _request_feedback_payload()
                rating = _clamp_rating(payload.get("rating"))
                # Already submitted: still allow Google redirect for high ratings.
                if already:
                    if rating is not None and rating >= GOOGLE_GATE_MIN_RATING:
                        if _wants_json():
                            return jsonify(
                                {
                                    "ok": True,
                                    "already": True,
                                    "rating": rating,
                                    "google_url": GOOGLE_REVIEW_URL,
                                    "redirect_google": True,
                                }
                            )
                        return redirect(GOOGLE_REVIEW_URL)
                    msg = "Feedback was already submitted for this link."
                    if _wants_json():
                        return jsonify({"ok": False, "error": msg, "already": True}), 409
                    return render_template(
                        "customer_feedback_public.html",
                        **_public_template_kwargs(
                            invite_dict, error=msg, done=True
                        ),
                    )
                try:
                    result = submit_feedback(
                        conn,
                        token,
                        rating=payload.get("rating"),
                        comment=str(payload.get("comment") or ""),
                        service_rating=payload.get("service_rating"),
                        food_rating=payload.get("food_rating"),
                        ambience_rating=payload.get("ambience_rating"),
                    )
                    if result.get("redirect_google"):
                        if _wants_json():
                            return jsonify(
                                {
                                    "ok": True,
                                    "rating": result["rating"],
                                    "google_url": GOOGLE_REVIEW_URL,
                                    "redirect_google": True,
                                    "submitted_at": result.get("submitted_at"),
                                }
                            )
                        return redirect(GOOGLE_REVIEW_URL)
                    if _wants_json():
                        return jsonify(
                            {
                                "ok": True,
                                "rating": result["rating"],
                                "redirect_google": False,
                                "thank_you": True,
                                "submitted_at": result.get("submitted_at"),
                            }
                        )
                    return render_template(
                        "customer_feedback_public.html",
                        **_public_template_kwargs(
                            invite_dict, thank_you=True, done=True
                        ),
                    )
                except ValueError as exc:
                    if _wants_json():
                        return jsonify({"ok": False, "error": str(exc)}), 400
                    return render_template(
                        "customer_feedback_public.html",
                        **_public_template_kwargs(
                            invite_dict, error=str(exc), done=False
                        ),
                    )
            # GET: if already submitted, still show star gate so high ratings can open Google.
            return render_template(
                "customer_feedback_public.html",
                **_public_template_kwargs(
                    invite_dict,
                    done=already,
                    thank_you=False,
                ),
            )
        finally:
            conn.close()
