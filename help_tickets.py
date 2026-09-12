"""Help → My Tickets support desk for Hotel Bell Elite (local)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from flask import jsonify, render_template, request

from db import get_db

STATUSES = ("open", "in_progress", "resolved")
PRIORITIES = ("high", "medium", "low")
TYPES = ("issue", "improvement")
MODULES = (
    "Billing",
    "Inventory",
    "Reports",
    "General",
    "Restaurant",
    "Bar",
    "Hotel",
    "Accounts",
    "Payroll",
    "Settings",
)

STATUS_ALIASES = {
    "under_review": "in_progress",
    "planned": "in_progress",
    "in-progress": "in_progress",
    "done": "resolved",
    "closed": "resolved",
}

STATUS_LABELS = {
    "open": "Open",
    "in_progress": "In Progress",
    "resolved": "Resolved",
}
PRIORITY_LABELS = {"high": "High", "medium": "Medium", "low": "Low"}
TYPE_LABELS = {"issue": "Issue", "improvement": "Improvement"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_help_tickets_schema(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS help_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_type TEXT NOT NULL DEFAULT 'issue',
            subject TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            module TEXT NOT NULL DEFAULT '',
            priority TEXT NOT NULL DEFAULT 'medium',
            status TEXT NOT NULL DEFAULT 'open',
            contact_email TEXT NOT NULL DEFAULT '',
            attachments_json TEXT NOT NULL DEFAULT '[]',
            developer_feedback TEXT NOT NULL DEFAULT '',
            created_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_help_tickets_created ON help_tickets(created_at DESC, id DESC)"
    )
    cols = {r[1] for r in conn.execute("PRAGMA table_info(help_tickets)").fetchall()}
    if "developer_feedback" not in cols:
        conn.execute("ALTER TABLE help_tickets ADD COLUMN developer_feedback TEXT NOT NULL DEFAULT ''")
        conn.commit()
    row = conn.execute("SELECT COUNT(*) AS c FROM help_tickets").fetchone()
    count = int(row["c"] if row and "c" in row.keys() else (row[0] if row else 0))
    if count == 0:
        seed = [
            ("issue", "Unable to save invoice", "Billing", "high", "open", "09 Sep 2026", "09 Sep 2026"),
            ("improvement", "Add dark mode option", "General", "low", "in_progress", "08 Sep 2026", "10 Sep 2026"),
            ("issue", "Stock count mismatch", "Inventory", "medium", "in_progress", "07 Sep 2026", "11 Sep 2026"),
            ("improvement", "Export report to Excel", "Reports", "medium", "open", "06 Sep 2026", "10 Sep 2026"),
            ("issue", "Login timeout on Wi-Fi", "General", "high", "resolved", "05 Sep 2026", "09 Sep 2026"),
        ]
        for t, subj, mod, pri, st, created, updated in seed:
            ca = datetime.strptime(created, "%d %b %Y").strftime("%Y-%m-%d 10:00:00")
            ua = datetime.strptime(updated, "%d %b %Y").strftime("%Y-%m-%d 16:00:00")
            conn.execute(
                """
                INSERT INTO help_tickets
                (ticket_type, subject, description, module, priority, status,
                 contact_email, attachments_json, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, '', '[]', NULL, ?, ?)
                """,
                (t, subj, "", mod, pri, st, ca, ua),
            )
        conn.commit()


def _fmt_date(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        return "—"
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:19] if len(raw) >= 19 else raw[:10], fmt).strftime("%d %b %Y")
        except ValueError:
            continue
    return raw[:10]


def _ticket_dict(row) -> dict[str, Any]:
    t = str(row["ticket_type"] or "issue")
    p = str(row["priority"] or "medium")
    s = str(row["status"] or "open").strip().lower()
    s = STATUS_ALIASES.get(s, s)
    if s not in STATUSES:
        s = "open"
    try:
        attachments = json.loads(row["attachments_json"] or "[]")
    except (TypeError, ValueError):
        attachments = []
    return {
        "id": int(row["id"]),
        "ticket_type": t,
        "type_label": TYPE_LABELS.get(t, t.title()),
        "subject": row["subject"] or "",
        "description": row["description"] or "",
        "module": row["module"] or "",
        "priority": p,
        "priority_label": PRIORITY_LABELS.get(p, p.title()),
        "status": s,
        "status_label": STATUS_LABELS.get(s, s.replace("_", " ").title()),
        "contact_email": row["contact_email"] or "",
        "attachments": attachments,
        "developer_feedback": row["developer_feedback"] if "developer_feedback" in row.keys() else "",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "created_on": _fmt_date(row["created_at"] or ""),
        "updated_on": _fmt_date(row["updated_at"] or ""),
    }


def list_help_tickets(
    conn,
    *,
    ticket_type: str = "all",
    status: str = "",
    q: str = "",
) -> list[dict[str, Any]]:
    ensure_help_tickets_schema(conn)
    sql = "SELECT * FROM help_tickets WHERE 1=1"
    args: list[Any] = []
    tt = (ticket_type or "all").strip().lower()
    if tt in ("issue", "improvement"):
        sql += " AND ticket_type = ?"
        args.append(tt)
    st = (status or "").strip().lower()
    if st in STATUSES:
        sql += " AND status = ?"
        args.append(st)
    query = (q or "").strip()
    if query:
        sql += " AND (subject LIKE ? OR module LIKE ? OR description LIKE ?)"
        like = f"%{query}%"
        args.extend([like, like, like])
    sql += " ORDER BY datetime(updated_at) DESC, id DESC"
    rows = conn.execute(sql, args).fetchall()
    return [_ticket_dict(r) for r in rows]


def create_help_ticket(conn, payload: dict[str, Any], *, user_id=None) -> dict[str, Any]:
    ensure_help_tickets_schema(conn)
    ticket_type = str(payload.get("ticket_type") or "issue").strip().lower()
    if ticket_type not in TYPES:
        ticket_type = "issue"
    subject = str(payload.get("subject") or "").strip()
    description = str(payload.get("description") or "").strip()[:1000]
    module = str(payload.get("module") or "").strip()
    priority = str(payload.get("priority") or "medium").strip().lower()
    if priority not in PRIORITIES:
        priority = "medium"
    status = str(payload.get("status") or "open").strip().lower()
    status = STATUS_ALIASES.get(status, status)
    if status not in STATUSES:
        status = "open"
    contact_email = str(payload.get("contact_email") or "").strip()
    attachments = payload.get("attachments") or []
    if not isinstance(attachments, list):
        attachments = []
    if not subject:
        raise ValueError("Subject is required.")
    if not description:
        raise ValueError("Description is required.")
    if not contact_email:
        raise ValueError("Contact email is required.")
    now = _now()
    cur = conn.execute(
        """
        INSERT INTO help_tickets
        (ticket_type, subject, description, module, priority, status,
         contact_email, attachments_json, created_by, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            ticket_type,
            subject[:200],
            description,
            module[:80],
            priority,
            status,
            contact_email[:200],
            json.dumps(attachments),
            user_id,
            now,
            now,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM help_tickets WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _ticket_dict(row)




def update_help_ticket(conn, ticket_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_help_tickets_schema(conn)
    row = conn.execute("SELECT * FROM help_tickets WHERE id = ?", (ticket_id,)).fetchone()
    if not row:
        raise ValueError("Ticket not found.")
    status = str(payload.get("status") or row["status"] or "open").strip().lower()
    status = STATUS_ALIASES.get(status, status)
    priority = str(payload.get("priority") or row["priority"] or "medium").strip().lower()
    feedback = payload.get("developer_feedback")
    if feedback is None:
        feedback = row["developer_feedback"] if "developer_feedback" in row.keys() else ""
    feedback = str(feedback or "")[:4000]
    if status not in STATUSES:
        status = row["status"]
    if priority not in PRIORITIES:
        priority = row["priority"]
    now = _now()
    conn.execute(
        "UPDATE help_tickets SET status = ?, priority = ?, developer_feedback = ?, updated_at = ? WHERE id = ?",
        (status, priority, feedback, now, ticket_id),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM help_tickets WHERE id = ?", (ticket_id,)).fetchone()
    return _ticket_dict(row)

def _require_help_desk_token() -> tuple[bool, str]:
    """Allow session users OR shared Help Desk token (never open unauthenticated write)."""
    expected = (os.environ.get("HELP_DESK_SYNC_TOKEN") or "").strip()
    got = (request.headers.get("X-Help-Desk-Token") or "").strip()
    if expected and got and got == expected:
        return True, "token"
    return False, "missing"


def register_help_tickets(app, *, get_current_user):
    @app.route("/help/tickets", endpoint="help_tickets")
    def help_tickets_page():
        user = get_current_user()
        email = ""
        if user:
            email = (
                str(user.get("email") or user.get("user_email") or user.get("username") or "")
            ).strip()
        return render_template(
            "help_tickets.html",
            de_nav_section="help",
            de_nav_help_view="tickets",
            help_contact_email=email or "user@dhiyaone.com",
            help_modules=MODULES,
            help_module_options=[("", "Select module")] + [(m, m) for m in MODULES],
            help_priority_options=[("high", "High"), ("medium", "Medium"), ("low", "Low")],
            help_statuses=[{"value": k, "label": v} for k, v in STATUS_LABELS.items()],
        )

    @app.route("/help/api/tickets", methods=["GET"], endpoint="help_api_tickets_list")
    def help_api_tickets_list():
        get_current_user()
        conn = get_db()
        try:
            items = list_help_tickets(
                conn,
                ticket_type=request.args.get("type") or "all",
                status=request.args.get("status") or "",
                q=request.args.get("q") or "",
            )
            return jsonify({"ok": True, "tickets": items})
        finally:
            conn.close()

    @app.route("/help/api/tickets", methods=["POST"], endpoint="help_api_tickets_create")
    def help_api_tickets_create():
        user = get_current_user()
        user_id = None
        if user:
            user_id = user.get("id") or user.get("user_id")
        data = request.get_json(silent=True) or {}
        if not data and request.form:
            data = {
                "ticket_type": request.form.get("ticket_type"),
                "subject": request.form.get("subject"),
                "description": request.form.get("description"),
                "module": request.form.get("module"),
                "priority": request.form.get("priority"),
                "contact_email": request.form.get("contact_email"),
            }
        names = []
        upload_dir = os.path.join(app.root_path, "static", "generated", "help_tickets")
        if request.files:
            os.makedirs(upload_dir, exist_ok=True)
            for f in request.files.getlist("files"):
                if not f or not f.filename:
                    continue
                safe = os.path.basename(f.filename)
                path = os.path.join(upload_dir, f"{int(datetime.now().timestamp())}_{safe}")
                f.save(path)
                names.append({"name": safe, "path": path})
        if names:
            data["attachments"] = names
        conn = get_db()
        try:
            ticket = create_help_ticket(conn, data, user_id=user_id)
            return jsonify({"ok": True, "ticket": ticket})
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        finally:
            conn.close()

    @app.route("/help/api/tickets/<int:ticket_id>", methods=["PATCH"], endpoint="help_api_tickets_patch")
    def help_api_tickets_patch(ticket_id: int):
        token_ok, _ = _require_help_desk_token()
        if not token_ok:
            # Fall back to normal logged-in app user
            user = get_current_user()
            if not user:
                return jsonify({"ok": False, "error": "Unauthorized"}), 401
        data = request.get_json(silent=True) or {}
        conn = get_db()
        try:
            ticket = update_help_ticket(conn, ticket_id, data)
            return jsonify({"ok": True, "ticket": ticket})
        except ValueError as exc:
            code = 404 if "not found" in str(exc).lower() else 400
            return jsonify({"ok": False, "error": str(exc)}), code
        finally:
            conn.close()
