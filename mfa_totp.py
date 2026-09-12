"""Opt-in TOTP MFA helpers for Hotel Bell Elite.

Secrets are encrypted at rest with Fernet. The key is derived via HKDF from
``MFA_SECRET_KEY`` (preferred) or Flask ``SECRET_KEY`` / env ``SECRET_KEY``.
Backup codes are stored only as HMAC-SHA256 hashes (app pepper).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Iterable, Optional

import pyotp
import qrcode
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

ISSUER_NAME = "Hotel Bell Elite"
MFA_PENDING_USER_ID = "mfa_pending_user_id"
MFA_PENDING_EXPIRES = "mfa_pending_expires"
MFA_PENDING_MUST_CHANGE = "mfa_pending_must_change"
MFA_PENDING_TOKEN = "mfa_pending_token"
MFA_SETUP_SECRET = "mfa_setup_secret"
MFA_PENDING_TTL_SEC = 10 * 60
BACKUP_CODE_COUNT = 8

def mfa_feature_enabled() -> bool:
    """Master switch. Dual auth is disabled unless HBE_MFA_ENABLED is 1/true/yes."""
    raw = (os.environ.get("HBE_MFA_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}



_ENC_PREFIX = "fernet1:"


def _secret_material() -> bytes:
    raw = (
        (os.environ.get("MFA_SECRET_KEY") or "").strip()
        or (os.environ.get("SECRET_KEY") or "").strip()
    )
    if not raw:
        # Last resort for unit tests / first boot before secret_key is wired.
        raw = "hotel-bell-elite-mfa-dev-only"
    return raw.encode("utf-8")


def _backup_pepper() -> bytes:
    return _secret_material() + b"|hbe-mfa-backup-v1"


def _fernet() -> Fernet:
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"hbe-mfa-totp-v1",
        info=b"mfa-secret-encryption",
    ).derive(_secret_material())
    return Fernet(base64.urlsafe_b64encode(derived))


def generate_secret() -> str:
    return pyotp.random_base32()


def encrypt_secret(plaintext: str) -> str:
    text = (plaintext or "").strip()
    if not text:
        return ""
    token = _fernet().encrypt(text.encode("utf-8")).decode("ascii")
    return _ENC_PREFIX + token


def decrypt_secret(stored: str) -> str:
    value = (stored or "").strip()
    if not value:
        return ""
    if value.startswith(_ENC_PREFIX):
        token = value[len(_ENC_PREFIX) :]
        try:
            return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
        except (InvalidToken, ValueError, TypeError):
            return ""
    # v1 plaintext fallback (legacy / unfinished migration)
    return value


def provisioning_uri(secret: str, account_name: str, *, issuer: str = ISSUER_NAME) -> str:
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=account_name or "user", issuer_name=issuer)


def verify_totp(secret: str, code: str, *, valid_window: int = 1) -> bool:
    cleaned = "".join(ch for ch in (code or "") if ch.isdigit())
    if len(cleaned) != 6 or not secret:
        return False
    try:
        return bool(pyotp.TOTP(secret).verify(cleaned, valid_window=valid_window))
    except Exception:
        return False


def generate_backup_codes(n: int = BACKUP_CODE_COUNT) -> list[str]:
    codes: list[str] = []
    for _ in range(max(1, int(n))):
        left = secrets.token_hex(2).upper()
        right = secrets.token_hex(2).upper()
        codes.append(f"{left}-{right}")
    return codes


def hash_backup_code(code: str) -> str:
    normalized = _normalize_backup_code(code)
    digest = hmac.new(_backup_pepper(), normalized.encode("utf-8"), hashlib.sha256).hexdigest()
    return digest


def _normalize_backup_code(code: str) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())


def backup_codes_to_storage(codes: Iterable[str]) -> str:
    hashed = [hash_backup_code(c) for c in codes]
    return json.dumps(hashed)


def load_backup_code_hashes(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if x]
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return [str(x) for x in data if x]


def verify_and_consume_backup_code(conn, user_id: int, code: str) -> bool:
    """Return True and persist remaining hashes if ``code`` matches a stored hash."""
    row = conn.execute(
        "SELECT mfa_backup_codes_hash FROM users WHERE id = ?",
        (int(user_id),),
    ).fetchone()
    if not row:
        return False
    hashes = load_backup_code_hashes(row["mfa_backup_codes_hash"] if "mfa_backup_codes_hash" in row.keys() else "")
    if not hashes:
        return False
    candidate = hash_backup_code(code)
    match_idx = None
    for idx, stored in enumerate(hashes):
        if hmac.compare_digest(stored, candidate):
            match_idx = idx
            break
    if match_idx is None:
        return False
    remaining = [h for i, h in enumerate(hashes) if i != match_idx]
    conn.execute(
        "UPDATE users SET mfa_backup_codes_hash = ? WHERE id = ?",
        (json.dumps(remaining), int(user_id)),
    )
    return True


def qr_png_bytes(uri: str) -> bytes:
    img = qrcode.make(uri)
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def qr_data_url(uri: str) -> str:
    png = qr_png_bytes(uri)
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def set_pending_mfa_session(session_obj, user_id: int, *, must_change_password: bool = False, ttl_sec: int = MFA_PENDING_TTL_SEC) -> str:
    """Store pending MFA state; returns opaque mfa_token for mobile clients."""
    token = secrets.token_urlsafe(32)
    session_obj[MFA_PENDING_USER_ID] = int(user_id)
    session_obj[MFA_PENDING_EXPIRES] = time.time() + max(60, int(ttl_sec))
    session_obj[MFA_PENDING_MUST_CHANGE] = bool(must_change_password)
    session_obj[MFA_PENDING_TOKEN] = token
    return token


def clear_pending_mfa_session(session_obj) -> None:
    for key in (
        MFA_PENDING_USER_ID,
        MFA_PENDING_EXPIRES,
        MFA_PENDING_MUST_CHANGE,
        MFA_PENDING_TOKEN,
        MFA_SETUP_SECRET,
    ):
        session_obj.pop(key, None)


def get_pending_mfa_user_id(session_obj, *, require_token: Optional[str] = None) -> Optional[int]:
    user_id = session_obj.get(MFA_PENDING_USER_ID)
    if user_id is None:
        return None
    expires = float(session_obj.get(MFA_PENDING_EXPIRES) or 0)
    if expires and time.time() > expires:
        clear_pending_mfa_session(session_obj)
        return None
    if require_token is not None:
        expected = session_obj.get(MFA_PENDING_TOKEN) or ""
        got = (require_token or "").strip()
        if not expected or not got or not hmac.compare_digest(str(expected), got):
            return None
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return None


def user_mfa_enabled(row) -> bool:
    if not mfa_feature_enabled():
        return False
    if row is None:
        return False
    try:
        if hasattr(row, "keys") and "mfa_enabled" in row.keys():
            return bool(int(row["mfa_enabled"] or 0))
    except Exception:
        pass
    try:
        return bool(int(getattr(row, "mfa_enabled", 0) or 0))
    except Exception:
        return False
