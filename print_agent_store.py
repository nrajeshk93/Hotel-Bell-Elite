"""Print Agent registration storage (Hotel Bell Elite ↔ Windows Print Agent).

Cloud clients on https://belleliteaccounts.com talk to a loopback agent on the
same Windows PC. Origins and browser pairing are derived from APP_BASE_URL.
API keys are stored as HMAC hashes; a sealed copy is kept so browser-pair can
still return the key. Plaintext is never persisted going forward.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

from secret_key import PUBLIC_DEFAULT_SECRET_KEY, get_secret_key

_SEAL_PREFIX = "enc1$"
_LEGACY_PEPPER = PUBLIC_DEFAULT_SECRET_KEY.encode("utf-8")


def ensure_print_agent_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS print_agents (
            agent_id TEXT PRIMARY KEY,
            business_id TEXT NOT NULL DEFAULT '',
            device_name TEXT NOT NULL DEFAULT '',
            windows_username TEXT NOT NULL DEFAULT '',
            agent_version TEXT NOT NULL DEFAULT '',
            api_key TEXT NOT NULL DEFAULT '',
            api_key_hash TEXT NOT NULL DEFAULT '',
            token_hash TEXT NOT NULL DEFAULT '',
            installed_printers_json TEXT NOT NULL DEFAULT '[]',
            mapped_printers_json TEXT NOT NULL DEFAULT '{}',
            last_seen_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT '',
            revoked INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(print_agents)").fetchall()
    }
    if "api_key" not in cols:
        conn.execute(
            "ALTER TABLE print_agents ADD COLUMN api_key TEXT NOT NULL DEFAULT ''"
        )
    if "api_key_hash" not in cols:
        conn.execute(
            "ALTER TABLE print_agents ADD COLUMN api_key_hash TEXT NOT NULL DEFAULT ''"
        )
    _migrate_plaintext_api_keys(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS print_agent_pairing_codes (
            code_hash TEXT PRIMARY KEY,
            created_by INTEGER NOT NULL DEFAULT 0,
            expires_at TEXT NOT NULL,
            used_at TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.commit()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _pepper() -> bytes:
    return get_secret_key().encode("utf-8")


def _hmac_hex(value: str, pepper: bytes) -> str:
    return hmac.new(pepper, (value or "").encode("utf-8"), hashlib.sha256).hexdigest()


def _hash_secret(value: str) -> str:
    return _hmac_hex(value, _pepper())


def _hashes_match(stored: str, value: str) -> bool:
    stored = stored or ""
    if not stored:
        return False
    current = _hash_secret(value)
    if len(stored) == len(current) and hmac.compare_digest(stored, current):
        return True
    legacy = _hmac_hex(value, _LEGACY_PEPPER)
    return len(stored) == len(legacy) and hmac.compare_digest(stored, legacy)


def _seal_secret(value: str) -> str:
    raw = (value or "").encode("utf-8")
    nonce = secrets.token_bytes(16)
    stream = b""
    counter = 0
    while len(stream) < len(raw):
        stream += hmac.new(
            _pepper(), nonce + b"print-agent-key" + counter.to_bytes(4, "big"), hashlib.sha256
        ).digest()
        counter += 1
    ct = bytes(a ^ b for a, b in zip(raw, stream[: len(raw)]))
    mac = hmac.new(_pepper(), nonce + ct, hashlib.sha256).digest()
    blob = base64.urlsafe_b64encode(nonce + mac + ct).decode("ascii")
    return _SEAL_PREFIX + blob


def _unseal_secret(stored: str) -> str:
    stored = stored or ""
    if not stored:
        return ""
    if not stored.startswith(_SEAL_PREFIX):
        return stored
    try:
        blob = base64.urlsafe_b64decode(stored[len(_SEAL_PREFIX) :].encode("ascii"))
    except (ValueError, TypeError):
        return ""
    if len(blob) < 48:
        return ""
    nonce, mac, ct = blob[:16], blob[16:48], blob[48:]
    expected = hmac.new(_pepper(), nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        return ""
    stream = b""
    counter = 0
    while len(stream) < len(ct):
        stream += hmac.new(
            _pepper(), nonce + b"print-agent-key" + counter.to_bytes(4, "big"), hashlib.sha256
        ).digest()
        counter += 1
    return bytes(a ^ b for a, b in zip(ct, stream[: len(ct)])).decode("utf-8")


def _migrate_plaintext_api_keys(conn) -> None:
    try:
        rows = conn.execute(
            "SELECT agent_id, api_key, api_key_hash FROM print_agents"
        ).fetchall()
    except Exception:
        return
    for row in rows:
        raw = (row["api_key"] or "").strip()
        if not raw:
            continue
        if raw.startswith(_SEAL_PREFIX):
            if not (row["api_key_hash"] or "").strip():
                plain = _unseal_secret(raw)
                if plain:
                    conn.execute(
                        "UPDATE print_agents SET api_key_hash = ? WHERE agent_id = ?",
                        (_hash_secret(plain), row["agent_id"]),
                    )
            continue
        conn.execute(
            """
            UPDATE print_agents
               SET api_key = ?, api_key_hash = ?
             WHERE agent_id = ?
            """,
            (_seal_secret(raw), _hash_secret(raw), row["agent_id"]),
        )


def _issue_token(agent_id: str, business_id: str) -> str:
    raw = secrets.token_urlsafe(32)
    return f"hpa_{agent_id[:8]}_{raw}"


def default_print_agent_origins(request_host_url: str | None = None) -> list[str]:
    """Origins allowed to call the local Print Agent from the browser."""
    origins: list[str] = []

    def add(url: str | None):
        u = (url or "").strip().rstrip("/")
        if u and u not in origins:
            origins.append(u)

    env_list = (os.environ.get("PRINT_AGENT_ALLOWED_ORIGINS") or "").split(",")
    for item in env_list:
        add(item)

    add((os.environ.get("APP_BASE_URL") or "").strip().rstrip("/"))

    # Production cloud app (primary client surface)
    add("https://belleliteaccounts.com")
    add("https://www.belleliteaccounts.com")

    # Local development
    add("http://127.0.0.1:8002")
    add("http://localhost:8002")

    if request_host_url:
        try:
            parsed = urlparse(request_host_url)
            if parsed.scheme and parsed.netloc:
                add(f"{parsed.scheme}://{parsed.netloc}")
        except Exception:
            pass

    return origins


def register_print_agent(conn, payload: dict, request_host_url: str | None = None) -> dict:
    ensure_print_agent_schema(conn)
    agent_id = str(payload.get("agentId") or payload.get("agent_id") or "").strip()
    business_id = str(payload.get("businessId") or payload.get("business_id") or "").strip()
    if not agent_id:
        return {"ok": False, "error": "agentId is required."}
    if not business_id:
        return {"ok": False, "error": "businessId is required."}

    device_name = str(payload.get("deviceName") or payload.get("device_name") or "")[:120]
    windows_username = str(payload.get("windowsUsername") or payload.get("windows_username") or "")[
        :120
    ]
    agent_version = str(payload.get("agentVersion") or payload.get("agent_version") or "")[:40]
    printers = payload.get("installedPrinters") or payload.get("installed_printers") or []
    if not isinstance(printers, list):
        printers = []
    printers_json = json.dumps([str(p)[:160] for p in printers[:80]])

    api_key = secrets.token_urlsafe(24)
    token = _issue_token(agent_id, business_id)
    stamp = _now()
    sealed = _seal_secret(api_key)
    key_hash = _hash_secret(api_key)
    token_hash = _hash_secret(token)

    existing = conn.execute(
        "SELECT agent_id, api_key, api_key_hash FROM print_agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if existing:
        presented = str(payload.get("apiKey") or payload.get("api_key") or "").strip()
        if not presented or not _hashes_match(existing["api_key_hash"] or "", presented):
            return {"ok": False, "error": "agent already registered."}
        api_key = _unseal_secret(existing["api_key"] or "") or api_key
        conn.execute(
            """
            UPDATE print_agents
            SET business_id = ?, device_name = ?, windows_username = ?, agent_version = ?,
                token_hash = ?, installed_printers_json = ?,
                last_seen_at = ?, updated_at = ?, revoked = 0
            WHERE agent_id = ?
            """,
            (
                business_id,
                device_name,
                windows_username,
                agent_version,
                token_hash,
                printers_json,
                stamp,
                stamp,
                agent_id,
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO print_agents (
                agent_id, business_id, device_name, windows_username, agent_version,
                api_key, api_key_hash, token_hash, installed_printers_json,
                last_seen_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                business_id,
                device_name,
                windows_username,
                agent_version,
                sealed,
                key_hash,
                token_hash,
                printers_json,
                stamp,
                stamp,
                stamp,
            ),
        )
    conn.commit()

    origins = default_print_agent_origins(request_host_url)
    return {
        "ok": True,
        "token": token,
        "apiKey": api_key,
        "allowedOrigins": origins,
        "agentId": agent_id,
        "backendBaseUrl": (os.environ.get("APP_BASE_URL") or "https://belleliteaccounts.com").rstrip(
            "/"
        ),
        "localPort": 4567,
    }


def verify_print_agent_bearer(conn, agent_id: str, bearer_token: str | None) -> bool:
    ensure_print_agent_schema(conn)
    aid = str(agent_id or "").strip()
    if not aid or not bearer_token:
        return False
    row = conn.execute(
        "SELECT token_hash, revoked FROM print_agents WHERE agent_id = ?",
        (aid,),
    ).fetchone()
    if not row or int(row["revoked"] or 0) == 1:
        return False
    return _hashes_match(row["token_hash"] or "", bearer_token)



def business_has_enrolled_agent(conn, business_id: str) -> bool:
    """True when this business already has a live Print Agent row."""
    ensure_print_agent_schema(conn)
    biz = str(business_id or "").strip()
    if not biz:
        return False
    row = conn.execute(
        """
        SELECT 1 FROM print_agents
        WHERE revoked = 0 AND business_id = ?
        LIMIT 1
        """,
        (biz,),
    ).fetchone()
    return bool(row)


def heartbeat_print_agent(conn, payload: dict, bearer_token: str | None) -> dict:
    ensure_print_agent_schema(conn)
    agent_id = str(payload.get("agentId") or payload.get("agent_id") or "").strip()
    if not agent_id:
        return {"ok": False, "error": "agentId is required."}

    row = conn.execute(
        "SELECT token_hash, revoked FROM print_agents WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    if not row or int(row["revoked"] or 0) == 1:
        return {
            "ok": False,
            "error": "Unknown or revoked agent.",
            "reregister": True,
        }
    if not bearer_token or not _hashes_match(row["token_hash"] or "", bearer_token):
        return {"ok": False, "error": "Invalid token.", "reregister": True}

    current_hash = _hash_secret(bearer_token)
    if (row["token_hash"] or "") != current_hash:
        conn.execute(
            "UPDATE print_agents SET token_hash = ? WHERE agent_id = ?",
            (current_hash, agent_id),
        )

    mapped = payload.get("printers") or {}
    if not isinstance(mapped, dict):
        mapped = {}
    installed = payload.get("installedPrinters") or payload.get("installed_printers") or []
    if not isinstance(installed, list):
        installed = []
    stamp = _now()
    conn.execute(
        """
        UPDATE print_agents
        SET mapped_printers_json = ?,
            installed_printers_json = ?,
            agent_version = COALESCE(?, agent_version),
            last_seen_at = ?,
            updated_at = ?
        WHERE agent_id = ?
        """,
        (
            json.dumps({str(k): str(v)[:160] for k, v in mapped.items()}),
            json.dumps([str(p)[:160] for p in installed[:80]]),
            str(payload.get("version") or "")[:40] or None,
            stamp,
            stamp,
            agent_id,
        ),
    )
    conn.commit()
    return {
        "ok": True,
        "serverTime": stamp,
        "allowedOrigins": default_print_agent_origins(),
        "backendBaseUrl": (os.environ.get("APP_BASE_URL") or "https://belleliteaccounts.com").rstrip(
            "/"
        ),
    }


def browser_pair_print_agent(
    conn, business_id: str | None = None, agent_id: str | None = None
) -> dict:
    """Return local-agent credentials for a logged-in cloud browser session.

    Prefer ``agent_id`` when the browser already discovered the loopback agent on
    this PC — otherwise the newest heartbeat for the business may belong to a
    different workstation and pairing silently breaks.
    """
    ensure_print_agent_schema(conn)
    wanted_id = (agent_id or "").strip()
    if wanted_id:
        row = conn.execute(
            """
            SELECT agent_id, api_key, api_key_hash, device_name, last_seen_at, business_id,
                   mapped_printers_json
            FROM print_agents
            WHERE revoked = 0 AND agent_id = ? AND api_key != ''
            LIMIT 1
            """,
            (wanted_id,),
        ).fetchone()
    else:
        biz = (business_id or "").strip()
        if biz:
            row = conn.execute(
                """
                SELECT agent_id, api_key, api_key_hash, device_name, last_seen_at, business_id,
                       mapped_printers_json
                FROM print_agents
                WHERE revoked = 0 AND business_id = ? AND api_key != ''
                ORDER BY datetime(last_seen_at) DESC, datetime(updated_at) DESC
                LIMIT 1
                """,
                (biz,),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT agent_id, api_key, api_key_hash, device_name, last_seen_at, business_id,
                       mapped_printers_json
                FROM print_agents
                WHERE revoked = 0 AND api_key != ''
                ORDER BY datetime(last_seen_at) DESC, datetime(updated_at) DESC
                LIMIT 1
                """
            ).fetchone()

    stored = (row["api_key"] if row else "") or ""
    api_key = _unseal_secret(stored) if stored else ""
    if not row or not api_key:
        return {
            "ok": False,
            "error": "No Print Agent registered for this business. Install Hotel Print Agent on this PC and click Register.",
            "localBaseUrl": "http://127.0.0.1:4567",
            "allowedOrigins": default_print_agent_origins(),
        }

    mapped = {}
    try:
        raw = row["mapped_printers_json"] if "mapped_printers_json" in row.keys() else "{}"
        parsed = json.loads(raw or "{}")
        if isinstance(parsed, dict):
            mapped = {str(k): str(v or "") for k, v in parsed.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        mapped = {}

    return {
        "ok": True,
        "agentId": row["agent_id"],
        "apiKey": api_key,
        "deviceName": row["device_name"] or "",
        "businessId": row["business_id"] or "",
        "lastSeenAt": row["last_seen_at"] or "",
        "mappedPrinters": mapped,
        "localBaseUrl": "http://127.0.0.1:4567",
        "port": 4567,
        "allowedOrigins": default_print_agent_origins(),
    }


def print_agent_latest_update(current_version: str) -> dict:
    latest = os.environ.get("PRINT_AGENT_LATEST_VERSION") or "1.0.0"
    return {
        "updateAvailable": False,
        "latestVersion": latest,
        "currentVersion": current_version or "",
        "releaseNotes": "",
        "downloadUrl": os.environ.get("PRINT_AGENT_DOWNLOAD_URL") or "",
        "message": "You are up to date.",
        "checkedAt": int(time.time()),
    }

def existing_agent_accepts_key(conn, payload: dict) -> bool:
    """True when this is a re-register of an enrolled agent presenting its API key."""
    ensure_print_agent_schema(conn)
    agent_id = str(payload.get("agentId") or payload.get("agent_id") or "").strip()
    presented = str(payload.get("apiKey") or payload.get("api_key") or "").strip()
    if not agent_id or not presented:
        return False
    row = conn.execute(
        "SELECT api_key_hash, revoked FROM print_agents WHERE agent_id = ?",
        (agent_id,),
    ).fetchone()
    if not row or int(row["revoked"] or 0) == 1:
        return False
    return _hashes_match(row["api_key_hash"] or "", presented)


def create_print_agent_pairing_code(conn, created_by: int, ttl_seconds: int = 900) -> dict:
    """Short-lived one-time code for a new Print Agent register (no session)."""
    ensure_print_agent_schema(conn)
    raw = secrets.token_hex(4).upper()
    expires = (datetime.now() + timedelta(seconds=int(ttl_seconds or 900))).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn.execute(
        """
        INSERT INTO print_agent_pairing_codes (code_hash, created_by, expires_at)
        VALUES (?, ?, ?)
        """,
        (_hash_secret(raw), int(created_by or 0), expires),
    )
    conn.commit()
    return {
        "ok": True,
        "pairingCode": raw,
        "expiresAt": expires,
        "ttlSeconds": int(ttl_seconds or 900),
    }


def consume_print_agent_pairing_code(conn, code: str) -> bool:
    code = str(code or "").strip().upper()
    if not code:
        return False
    ensure_print_agent_schema(conn)
    now = _now()
    rows = conn.execute(
        """
        SELECT code_hash, expires_at FROM print_agent_pairing_codes
        WHERE used_at = ''
        """
    ).fetchall()
    for row in rows:
        if not _hashes_match(row["code_hash"] or "", code):
            continue
        if (row["expires_at"] or "") < now:
            continue
        conn.execute(
            "UPDATE print_agent_pairing_codes SET used_at = ? WHERE code_hash = ?",
            (now, row["code_hash"]),
        )
        conn.commit()
        return True
    return False

