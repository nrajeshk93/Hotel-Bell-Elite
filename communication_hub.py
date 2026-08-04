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
            # Enrich media metadata when a mirror row landed first without filenames.
            if media_filename or media_mime or media_size:
                conn.execute(
                    """UPDATE wa_messages
                       SET media_mime = CASE WHEN COALESCE(media_mime, '') = '' THEN ? ELSE media_mime END,
                           media_filename = CASE WHEN COALESCE(media_filename, '') = '' THEN ? ELSE media_filename END,
                           media_size = CASE WHEN COALESCE(media_size, 0) = 0 THEN ? ELSE media_size END,
                           body = CASE
                             WHEN COALESCE(body, '') IN ('', 'Photo', 'Document', 'image', 'document')
                                  AND COALESCE(?, '') != '' THEN ?
                             ELSE body
                           END
                       WHERE id = ?""",
                    (
                        media_mime or "",
                        media_filename or "",
                        int(media_size or 0),
                        body or "",
                        body or "",
                        existing["id"],
                    ),
                )
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
        direction="out",
        body=body,
        message_type=message_type,
        media_mime=media_mime,
        media_filename=media_filename,
        media_size=media_size,
        wa_message_id=wa_message_id,
        status=status,
        error=error,
        created_by=created_by,
        bump_unread=False,
    )


def build_hub_home_notification(conn) -> dict | None:
    """Return a home-bell notification dict when hub conversations have unread inbound."""
    ensure_communication_hub_schema(conn)
    total = int(
        (
            conn.execute(
                "SELECT COALESCE(SUM(unread_count), 0) AS c FROM wa_conversations"
            ).fetchone()
            or {"c": 0}
        )["c"]
        or 0
    )
    if total <= 0:
        return None
    top = conn.execute(
        """SELECT display_name, phone_e164, last_preview, unread_count
           FROM wa_conversations
           WHERE COALESCE(unread_count, 0) > 0
           ORDER BY COALESCE(last_message_at, '') DESC, id DESC
           LIMIT 1"""
    ).fetchone()
    label = ""
    preview = ""
    if top:
        label = str(top["display_name"] or top["phone_e164"] or "WhatsApp").strip() or "WhatsApp"
        preview = str(top["last_preview"] or "").strip()
    if total == 1:
        title = f"New message from {label}"
        body = preview or "Open Communication Hub to reply."
    else:
        title = f"{total} new WhatsApp messages"
        body = f"Latest from {label}" + (f": {preview}" if preview else ".")
    return {
        "id": "communication-hub-unread",
        "title": title,
        "body": body[:180],
        "href": "",  # filled by caller with url_for
    }


def export_hub_mirror_payload(conn) -> dict:
    """Snapshot conversations + messages for local-dev mirror pull."""
    ensure_communication_hub_schema(conn)
    conversations = list_conversations(conn)
    rows = conn.execute(
        """
        SELECT m.direction, m.message_type, m.body, m.wa_message_id, m.status,
               m.error, m.media_mime, m.media_filename, m.media_size,
               m.created_at, c.phone_e164, c.display_name
        FROM wa_messages m
        JOIN wa_conversations c ON c.id = m.conversation_id
        ORDER BY m.id ASC
        """
    ).fetchall()
    messages = []
    for row in rows:
        messages.append(
            {
                "phone": row["phone_e164"] or "",
                "display_name": row["display_name"] or "",
                "direction": row["direction"] or "in",
                "message_type": row["message_type"] or "text",
                "body": row["body"] or "",
                "wa_message_id": row["wa_message_id"] or "",
                "status": row["status"] or "",
                "error": row["error"] or "",
                "media_mime": row["media_mime"] or "",
                "media_filename": row["media_filename"] or "",
                "media_size": int(row["media_size"] or 0),
                "created_at": row["created_at"] or "",
            }
        )
    return {"ok": True, "conversations": conversations, "messages": messages}


def pull_hub_mirror_into(conn) -> int:
    """Pull WhatsApp hub rows from production into this DB (local preview).

    Meta webhooks only hit APP_BASE_URL / production. Local ``127.0.0.1`` never
    receives them unless we mirror. Opt-in via ``HUB_MIRROR_URL`` + ``HUB_MIRROR_TOKEN``.
    """
    import os

    import requests

    base = (os.environ.get("HUB_MIRROR_URL") or "").strip().rstrip("/")
    token = (os.environ.get("HUB_MIRROR_TOKEN") or "").strip()
    if not base or not token:
        return 0
    url = base + "/communication-hub/api/mirror-export"
    try:
        response = requests.get(
            url,
            headers={"X-Hub-Mirror-Token": token, "Accept": "application/json"},
            timeout=12,
        )
    except requests.RequestException as exc:
        log.warning("Hub mirror pull failed: %s", exc)
        return 0
    if response.status_code != 200:
        log.warning("Hub mirror pull HTTP %s", response.status_code)
        return 0
    try:
        payload = response.json()
    except ValueError:
        return 0
    if not isinstance(payload, dict) or not payload.get("ok"):
        return 0

    ensure_communication_hub_schema(conn)
    added = 0
    for item in payload.get("messages") or []:
        if not isinstance(item, dict):
            continue
        phone = wa.normalise_whatsapp_number(item.get("phone") or "")
        if not phone:
            continue
        wa_id = str(item.get("wa_message_id") or "").strip()
        if wa_id:
            exists = conn.execute(
                "SELECT 1 FROM wa_messages WHERE wa_message_id = ? LIMIT 1",
                (wa_id,),
            ).fetchone()
            if exists:
                continue
        direction = "out" if str(item.get("direction") or "").lower() == "out" else "in"
        display_name = str(item.get("display_name") or "").strip()
        conversation = get_or_create_conversation(conn, phone, display_name=display_name)
        if not conversation:
            continue
        before = conn.execute(
            "SELECT COUNT(*) AS c FROM wa_messages WHERE conversation_id = ?",
            (conversation["id"],),
        ).fetchone()["c"]
        append_message(
            conn,
            conversation["id"],
            direction=direction,
            body=str(item.get("body") or ""),
            message_type=str(item.get("message_type") or "text"),
            media_mime=str(item.get("media_mime") or ""),
            media_filename=str(item.get("media_filename") or ""),
            media_size=int(item.get("media_size") or 0),
            wa_message_id=wa_id,
            status=str(item.get("status") or ("sent" if direction == "out" else "delivered")),
            error=str(item.get("error") or ""),
            bump_unread=(direction == "in"),
        )
        after = conn.execute(
            "SELECT COUNT(*) AS c FROM wa_messages WHERE conversation_id = ?",
            (conversation["id"],),
        ).fetchone()["c"]
        if after > before:
            added += 1

    # Sync previews/timestamps from production, but never overwrite local unread.
    # Forcing remote unread_count re-marked conversations as unread after open
    # (local mark_read → later poll → unread restored from prod).
    preview_synced = 0
    for item in payload.get("conversations") or []:
        if not isinstance(item, dict):
            continue
        phone = wa.normalise_whatsapp_number(
            item.get("phone") or item.get("phone_e164") or ""
        )
        if not phone:
            continue
        preview = str(item.get("last_preview") or "").strip()
        last_at = str(item.get("last_message_at") or "").strip()
        if not preview and not last_at:
            continue
        row = conn.execute(
            "SELECT id, unread_count FROM wa_conversations WHERE phone_e164 = ?",
            (phone,),
        ).fetchone()
        if not row:
            continue
        remote_unread = int(item.get("unread_count") or 0)
        local_unread = int(row["unread_count"] or 0)
        conn.execute(
            """UPDATE wa_conversations
               SET last_preview = CASE WHEN ? != '' THEN ? ELSE last_preview END,
                   last_message_at = CASE WHEN ? != '' THEN ? ELSE last_message_at END,
                   updated_at = datetime('now','localtime')
             WHERE id = ?""",
            (preview, preview, last_at, last_at, row["id"]),
        )
        preview_synced += 1
    if added or preview_synced:
        conn.commit()
    return added


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


_ALLOWED_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
}
_ALLOWED_DOC_TYPES = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "text/plain",
}
_MAX_ATTACH_BYTES = 16 * 1024 * 1024


def send_conversation_attachment(
    conn,
    conversation_id: int,
    *,
    file_storage,
    caption: str = "",
    user_id=None,
) -> tuple[bool, str, dict]:
    """Upload a file to WhatsApp and send it on the open conversation."""
    import os
    import tempfile

    conversation = get_conversation(conn, conversation_id)
    if not conversation:
        return False, "Conversation not found.", {}
    if not wa.whatsapp_configured():
        return False, "WhatsApp API is not configured.", {}
    if file_storage is None or not getattr(file_storage, "filename", None):
        return False, "Choose a file to attach.", {}

    filename = os.path.basename(str(file_storage.filename or "attachment")).strip() or "attachment"
    mime = (getattr(file_storage, "mimetype", None) or "").strip().lower() or "application/octet-stream"
    if mime in _ALLOWED_IMAGE_TYPES or mime.startswith("image/"):
        media_type = "image"
        if mime not in _ALLOWED_IMAGE_TYPES:
            mime = "image/jpeg"
    elif mime in _ALLOWED_DOC_TYPES:
        media_type = "document"
    else:
        # Fall back to document for unknown but allow common extensions.
        ext = os.path.splitext(filename)[1].lower()
        if ext in {".jpg", ".jpeg", ".png", ".webp"}:
            media_type = "image"
            mime = {".png": "image/png", ".webp": "image/webp"}.get(ext, "image/jpeg")
        elif ext in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt"}:
            media_type = "document"
            mime = {
                ".pdf": "application/pdf",
                ".doc": "application/msword",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ".xls": "application/vnd.ms-excel",
                ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                ".txt": "text/plain",
            }.get(ext, "application/octet-stream")
        else:
            return False, "Unsupported file type. Use an image or PDF/Office document.", {}

    tmp_path = ""
    try:
        suffix = os.path.splitext(filename)[1] or ""
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        os.close(fd)
        file_storage.save(tmp_path)
        size = os.path.getsize(tmp_path)
        if size <= 0:
            return False, "The selected file is empty.", {}
        if size > _MAX_ATTACH_BYTES:
            return False, "File is too large (max 16 MB).", {}

        ok_up, err_up, body_up = wa.upload_media_file(tmp_path, mime)
        media_id = ""
        if isinstance(body_up, dict):
            media_id = str(body_up.get("id") or "").strip()
        if not ok_up or not media_id:
            return False, err_up or "WhatsApp media upload failed.", {}

        ok, err, payload = wa.send_media_message(
            conversation["phone"],
            media_id=media_id,
            media_type=media_type,
            filename=filename if media_type == "document" else "",
            caption=caption,
        )
        wa_message_id = wa.first_message_id(payload) if ok else ""
        body_preview = (caption or "").strip() or filename
        if ok:
            message = append_message(
                conn,
                conversation_id,
                direction="out",
                body=body_preview,
                message_type=media_type,
                media_mime=mime,
                media_filename=filename,
                media_size=size,
                wa_message_id=wa_message_id,
                status="sent",
                created_by=user_id,
            )
            return True, "", {
                "conversation": get_conversation(conn, conversation_id),
                "message": message,
            }
        message = append_message(
            conn,
            conversation_id,
            direction="out",
            body=body_preview,
            message_type=media_type,
            media_mime=mime,
            media_filename=filename,
            media_size=size,
            status="failed",
            error=err or "Send failed",
            created_by=user_id,
        )
        return False, err or "Send failed", {
            "conversation": get_conversation(conn, conversation_id),
            "message": message,
        }
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


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
            pull_hub_mirror_into(conn)
            items = list_conversations(conn, search=search)
        finally:
            conn.close()
        return jsonify({"ok": True, "conversations": items})

    @app.route("/communication-hub/api/mirror-export", methods=["GET"])
    def communication_hub_api_mirror_export():
        """Token-gated export so local Flask can mirror live WhatsApp hub rows."""
        import os

        expected = (os.environ.get("HUB_MIRROR_TOKEN") or "").strip()
        got = (request.headers.get("X-Hub-Mirror-Token") or "").strip()
        if not expected or got != expected:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        conn = get_db()
        try:
            payload = export_hub_mirror_payload(conn)
        finally:
            conn.close()
        return jsonify(payload)

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
            pull_hub_mirror_into(conn)
            conversation = get_conversation(conn, conversation_id)
            if not conversation:
                # Phone-keyed mirror may create a different local id — resolve by rematch.
                pull_hub_mirror_into(conn)
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
        user = _get_user() if _get_user else None
        user_id = user.get("id") if user else None
        upload = request.files.get("file") or request.files.get("attachment")
        if upload and getattr(upload, "filename", None):
            caption = (
                request.form.get("caption")
                or request.form.get("text")
                or request.form.get("body")
                or ""
            )
            conn = get_db()
            try:
                ok, err, payload = send_conversation_attachment(
                    conn,
                    conversation_id,
                    file_storage=upload,
                    caption=caption,
                    user_id=user_id,
                )
                conn.commit()
            finally:
                conn.close()
            if not ok:
                return jsonify({"ok": False, "error": err, **payload}), 400
            return jsonify({"ok": True, **payload})

        data = request.get_json(silent=True) or {}
        text = data.get("text") or data.get("body") or data.get("message") or ""
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
