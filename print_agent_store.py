"""Print Agent registration storage (Hotel Bell Elite ↔ Windows Print Agent).

Cloud clients on https://belleliteaccounts.com talk to a loopback agent on the
same Windows PC. Origins and browser pairing are derived from APP_BASE_URL.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime
from urllib.parse import urlparse


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
    conn.commit()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _hash_secret(value: str) -> str:
    pepper = (os.environ.get("SECRET_KEY") or "hotel-bell-elite-dev-key-change-in-production").encode(
        "utf-8"
    )
    return hmac.new(pepper, (value or "").encode("utf-8"), hashlib.sha256).hexdigest()


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

    existing = conn.execute(
        "SELECT agent_id FROM print_agents WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE print_agents
            SET business_id = ?, device_name = ?, windows_username = ?, agent_version = ?,
                api_key = ?, api_key_hash = ?, token_hash = ?, installed_printers_json = ?,
                last_seen_at = ?, updated_at = ?, revoked = 0
            WHERE agent_id = ?
            """,
            (
                business_id,
                device_name,
                windows_username,
                agent_version,
                api_key,
                _hash_secret(api_key),
                _hash_secret(token),
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
                api_key,
                _hash_secret(api_key),
                _hash_secret(token),
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


def heartbeat_print_agent(conn, payload: dict, bearer_token: str | None) -> dict:
    ensure_print_agent_schema(conn)
    agent_id = str(payload.get("agentId") or payload.get("agent_id") or "").strip()
    if not agent_id:
        return {"ok": False, "error": "agentId is required."}

    row = conn.execute(
        "SELECT token_hash, revoked FROM print_agents WHERE agent_id = ?", (agent_id,)
    ).fetchone()
    if not row or int(row["revoked"] or 0) == 1:
        return {"ok": False, "error": "Unknown or revoked agent."}
    if not bearer_token or _hash_secret(bearer_token) != (row["token_hash"] or ""):
        return {"ok": False, "error": "Invalid token."}

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
            SELECT agent_id, api_key, device_name, last_seen_at, business_id,
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
                SELECT agent_id, api_key, device_name, last_seen_at, business_id,
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
                SELECT agent_id, api_key, device_name, last_seen_at, business_id,
                       mapped_printers_json
                FROM print_agents
                WHERE revoked = 0 AND api_key != ''
                ORDER BY datetime(last_seen_at) DESC, datetime(updated_at) DESC
                LIMIT 1
                """
            ).fetchone()

    if not row or not (row["api_key"] or "").strip():
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
        "apiKey": row["api_key"],
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
