"""Communication Hub — WhatsApp inbox for Hotel Bell Elite."""

from __future__ import annotations

import logging
from datetime import datetime

from flask import jsonify, render_template, request

import whatsapp_client as wa
from db import ensure_communication_hub_schema, get_db

log = logging.getLogger(__name__)

_PREVIEW_MAX = 120

_pop_auth_notice = None
_get_user = None


def _bind_helpers(*, pop_auth_notice, get_user):
    global _pop_auth_notice, _get_user
    _pop_auth_notice = pop_auth_notice
    _get_user = get_user


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _preview_text(body: str, message_type: str = "text") -> str:
    text = (body or "").strip()
    if not text:
        if message_type == "image":
            return "Photo"
        if message_type == "document":
            return "Document"
        if message_type == "audio":
            return "Audio"
        return "Message"
    text = " ".join(text.split())
    if len(text) > _PREVIEW_MAX:
        return text[: _PREVIEW_MAX - 1] + "…"
    return text


def _display_label(row) -> str:
    name = (row["display_name"] or "").strip() if row else ""
    phone = (row["phone_e164"] or "").strip() if row else ""
    return name or phone or "Unknown"


def _conversation_dict(row) -> dict:
    return {
        "id": int(row["id"]),
        "phone": row["phone_e164"] or "",
        "display_name": row["display_name"] or "",
        "label": _display_label(row),
        "last_message_at": row["last_message_at"] or "",
        "last_preview": row["last_preview"] or "",
        "unread_count": int(row["unread_count"] or 0),
        "updated_at": row["updated_at"] or "",
    }


def _message_dict(row) -> dict:
    return {
        "id": int(row["id"]),
        "conversation_id": int(row["conversation_id"]),
        "direction": row["direction"] or "",
        "message_type": row["message_type"] or "text",
        "body": row["body"] or "",
        "media_mime": row["media_mime"] or "",
        "media_filename": row["media_filename"] or "",
        "media_size": int(row["media_size"] or 0),
        "wa_message_id": row["wa_message_id"] or "",
        "status": row["status"] or "",
        "error": row["error"] or "",
        "created_at": row["created_at"] or "",
        "created_by": row["created_by"],
    }


def get_or_create_conversation(conn, phone: str, display_name: str = "") -> dict | None:
    phone_e164 = wa.normalise_whatsapp_number(phone)
    if not phone_e164:
        return None
    ensure_communication_hub_schema(conn)
    row = conn.execute(
        "SELECT * FROM wa_conversations WHERE phone_e164 = ?",
        (phone_e164,),
    ).fetchone()
    name = (display_name or "").strip()
    if row:
        if name and not (row["display_name"] or "").strip():
            conn.execute(
                """UPDATE wa_conversations
                   SET display_name = ?, updated_at = datetime('now','localtime')
                   WHERE id = ?""",
                (name, row["id"]),
            )
            row = conn.execute(
                "SELECT * FROM wa_conversations WHERE id = ?",
                (row["id"],),
            ).fetchone()
        return _conversation_dict(row)
    cur = conn.execute(
        """INSERT INTO wa_conversations (phone_e164, display_name)
           VALUES (?, ?)""",
        (phone_e164, name),
    )
    row = conn.execute(
        "SELECT * FROM wa_conversations WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return _conversation_dict(row)


def list_conversations(conn, search: str = "") -> list[dict]:
    ensure_communication_hub_schema(conn)
    q = (search or "").strip().lower()
    rows = conn.execute(
        """SELECT * FROM wa_conversations
           ORDER BY COALESCE(last_message_at, updated_at, created_at) DESC, id DESC"""
    ).fetchall()
    items = [_conversation_dict(row) for row in rows]
    if not q:
        return items
    out = []
    for item in items:
        blob = " ".join(
            [
                item.get("label") or "",
                item.get("phone") or "",
                item.get("display_name") or "",
                item.get("last_preview") or "",
            ]
        ).lower()
        if q in blob:
            out.append(item)
    return out


def get_conversation(conn, conversation_id: int):
    ensure_communication_hub_schema(conn)
    row = conn.execute(
        "SELECT * FROM wa_conversations WHERE id = ?",
        (int(conversation_id),),
    ).fetchone()
    return _conversation_dict(row) if row else None


def list_messages(conn, conversation_id: int, *, mark_read: bool = False) -> list[dict]:
    ensure_communication_hub_schema(conn)
    rows = conn.execute(
        """SELECT * FROM wa_messages
           WHERE conversation_id = ?
           ORDER BY created_at ASC, id ASC""",
        (int(conversation_id),),
    ).fetchall()
    if mark_read:
        conn.execute(
            """UPDATE wa_conversations
               SET unread_count = 0, updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (int(conversation_id),),
        )
    return [_message_dict(row) for row in rows]


def append_message(
    conn,
    conversation_id: int,
    *,
    direction: str,
    body: str = "",
    message_type: str = "text",
    media_mime: str = "",
    media_filename: str = "",
    media_size: int = 0,
    wa_message_id: str = "",
    status: str = "sent",
    error: str = "",
    created_by=None,
    bump_unread: bool = False,
) -> dict | None:
    ensure_communication_hub_schema(conn)
    wa_id = (wa_message_id or "").strip() or None
    if wa_id:
        existing = conn.execute(
            "SELECT id FROM wa_messages WHERE wa_message_id = ?",
            (wa_id,),
        ).fetchone()
        if existing:
            row = conn.execute(
                "SELECT * FROM wa_messages WHERE id = ?",
                (existing["id"],),
            ).fetchone()
            return _message_dict(row) if row else None

    preview = _preview_text(body, message_type)
    stamp = _now()
    cur = conn.execute(
        """INSERT INTO wa_messages
           (conversation_id, direction, message_type, body, media_mime, media_filename,
            media_size, wa_message_id, status, error, created_at, created_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            int(conversation_id),
            direction,
            message_type or "text",
            body or "",
            media_mime or "",
            media_filename or "",
            int(media_size or 0),
            wa_id,
            status or "sent",
            error or "",
            stamp,
            created_by,
        ),
    )
    if bump_unread and direction == "in":
        conn.execute(
            """UPDATE wa_conversations
               SET last_message_at = ?, last_preview = ?,
                   unread_count = COALESCE(unread_count, 0) + 1,
                   updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (stamp, preview, int(conversation_id)),
        )
    else:
        conn.execute(
            """UPDATE wa_conversations
               SET last_message_at = ?, last_preview = ?,
                   updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (stamp, preview, int(conversation_id)),
        )
    row = conn.execute(
        "SELECT * FROM wa_messages WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return _message_dict(row) if row else None


def ingest_inbound_whatsapp_message(
    conn,
    *,
    phone: str,
    body: str = "",
    message_type: str = "text",
    wa_message_id: str = "",
    display_name: str = "",
    media_mime: str = "",
    media_filename: str = "",
    media_size: int = 0,
) -> dict | None:
    conversation = get_or_create_conversation(conn, phone, display_name=display_name)
    if not conversation:
        return None
    return append_message(
        conn,
        conversation["id"],
        direction="in",
        body=body,
        message_type=message_type,
        media_mime=media_mime,
        media_filename=media_filename,
        media_size=media_size,
        wa_message_id=wa_message_id,
        status="delivered",
        bump_unread=True,
    )


def record_outbound_hub_message(
    conn,
    phone: str,
    body: str,
    *,
    wa_message_id: str = "",
    status: str = "sent",
    error: str = "",
    display_name: str = "",
    created_by=None,
    message_type: str = "text",
) -> dict | None:
    conversation = get_or_create_conversation(conn, phone, display_name=display_name)
    if not conversation:
        return None
    return append_message(
        conn,
        conversation["id"],
        direction="out",
        body=body,
        message_type=message_type,
        wa_message_id=wa_message_id,
        status=status,
        error=error,
        created_by=created_by,
        bump_unread=False,
    )


def send_conversation_text(conn, conversation_id: int, text: str, *, user_id=None) -> tuple[bool, str, dict]:
    conversation = get_conversation(conn, conversation_id)
    if not conversation:
        return False, "Conversation not found.", {}
    body = (text or "").strip()
    if not body:
        return False, "Message cannot be empty.", {}
    if not wa.whatsapp_configured():
        return False, "WhatsApp API is not configured.", {}

    ok, err, payload = wa.send_text_message(conversation["phone"], body)
    wa_message_id = ""
    if isinstance(payload, dict):
        messages = payload.get("messages") or []
        if messages and isinstance(messages[0], dict):
            wa_message_id = str(messages[0].get("id") or "").strip()

    if ok:
        message = append_message(
            conn,
            conversation_id,
            direction="out",
            body=body,
            message_type="text",
            wa_message_id=wa_message_id,
            status="sent",
            created_by=user_id,
        )
        return True, "", {"conversation": get_conversation(conn, conversation_id), "message": message}

    message = append_message(
        conn,
        conversation_id,
        direction="out",
        body=body,
        message_type="text",
        status="failed",
        error=err or "Send failed",
        created_by=user_id,
    )
    return False, err or "Send failed", {
        "conversation": get_conversation(conn, conversation_id),
        "message": message,
    }


def register_communication_hub(app, *, pop_auth_notice, get_user):
    _bind_helpers(pop_auth_notice=pop_auth_notice, get_user=get_user)

    def _page_render(**kwargs):
        kwargs.setdefault("auth_notice", _pop_auth_notice() if _pop_auth_notice else None)
        kwargs.setdefault("de_nav_section", "communication_hub")
        kwargs.setdefault("de_nav_communication_hub_view", "inbox")
        return render_template("communication_hub.html", **kwargs)

    @app.route("/communication-hub")
    def communication_hub():
        conn = get_db()
        try:
            ensure_communication_hub_schema(conn)
            conversations = list_conversations(conn)
        finally:
            conn.close()
        user = _get_user() if _get_user else None
        return _page_render(
            page_title="Communication Hub",
            conversations=conversations,
            whatsapp_configured=wa.whatsapp_configured(),
            current_user_name=(
                (user.get("full_name") or user.get("username") or "User").strip()
                if user
                else "User"
            ),
        )

    @app.route("/communication-hub/api/conversations", methods=["GET"])
    def communication_hub_api_conversations():
        search = (request.args.get("q") or request.args.get("search") or "").strip()
        conn = get_db()
        try:
            items = list_conversations(conn, search=search)
        finally:
            conn.close()
        return jsonify({"ok": True, "conversations": items})

    @app.route("/communication-hub/api/conversations", methods=["POST"])
    def communication_hub_api_conversation_create():
        data = request.get_json(silent=True) or {}
        phone = data.get("phone") or data.get("mobile") or ""
        display_name = (data.get("display_name") or data.get("name") or "").strip()
        phone_e164 = wa.normalise_whatsapp_number(phone)
        if not phone_e164:
            return jsonify({"ok": False, "error": "Enter a valid WhatsApp phone number."}), 400
        conn = get_db()
        try:
            conversation = get_or_create_conversation(conn, phone_e164, display_name=display_name)
            conn.commit()
        finally:
            conn.close()
        if not conversation:
            return jsonify({"ok": False, "error": "Unable to open conversation."}), 400
        return jsonify({"ok": True, "conversation": conversation})

    @app.route("/communication-hub/api/conversations/<int:conversation_id>/messages", methods=["GET"])
    def communication_hub_api_messages(conversation_id):
        conn = get_db()
        try:
            conversation = get_conversation(conn, conversation_id)
            if not conversation:
                return jsonify({"ok": False, "error": "Conversation not found."}), 404
            messages = list_messages(conn, conversation_id, mark_read=True)
            conversation = get_conversation(conn, conversation_id)
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True, "conversation": conversation, "messages": messages})

    @app.route("/communication-hub/api/conversations/<int:conversation_id>/messages", methods=["POST"])
    def communication_hub_api_message_send(conversation_id):
        data = request.get_json(silent=True) or {}
        text = data.get("text") or data.get("body") or data.get("message") or ""
        user = _get_user() if _get_user else None
        user_id = user.get("id") if user else None
        conn = get_db()
        try:
            ok, err, payload = send_conversation_text(
                conn, conversation_id, text, user_id=user_id
            )
            conn.commit()
        finally:
            conn.close()
        if not ok:
            return jsonify({"ok": False, "error": err, **payload}), 400
        return jsonify({"ok": True, **payload})
