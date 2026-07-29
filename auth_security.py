"""Login lockout, CAPTCHA, and unlock-token helpers."""

from __future__ import annotations

import hashlib
import hmac
import io
import random
import secrets
import threading
import time
from datetime import datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from werkzeug.security import check_password_hash

# Thresholds
CAPTCHA_AFTER_FAILURES = 2
LOCK_AFTER_FAILURES = 3
UNLOCK_TOKEN_TTL_HOURS = 1
IP_THROTTLE_LIMIT = 20
IP_THROTTLE_WINDOW_SEC = 15 * 60

# Argon2id hasher (argon2-cffi defaults: type=ID, time_cost=2, memory_cost=65536, parallelism=4).
_PASSWORD_HASHER = PasswordHasher()

# Precomputed dummy hash so missing-user checks take similar time.
_DUMMY_PASSWORD_HASH = _PASSWORD_HASHER.hash("hotel-bell-elite-dummy-password")

_ip_lock = threading.Lock()
_ip_attempts: dict[str, list[float]] = {}

CAPTCHA_SESSION_ANSWER = "login_captcha_answer"
CAPTCHA_SESSION_EXPIRES = "login_captcha_expires"
CAPTCHA_TTL_SEC = 10 * 60


def sql_now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def is_account_locked(row) -> bool:
    if not row:
        return False
    locked_at = row["locked_at"] if "locked_at" in row.keys() else None
    return bool(locked_at)


def captcha_is_required(row) -> bool:
    if not row:
        return False
    if is_account_locked(row):
        return False
    try:
        return int(row["captcha_required"] or 0) == 1
    except (KeyError, TypeError, ValueError):
        return False


def hash_password(password: str) -> str:
    """Hash a password with Argon2id for storage."""
    return _PASSWORD_HASHER.hash(password or "")


def _is_argon2_hash(password_hash: str) -> bool:
    return bool(password_hash) and str(password_hash).startswith("$argon2")


def password_needs_rehash(password_hash: str | None) -> bool:
    """True when the stored hash should be upgraded to current Argon2id params."""
    if not password_hash:
        return True
    if not _is_argon2_hash(password_hash):
        return True
    try:
        return bool(_PASSWORD_HASHER.check_needs_rehash(password_hash))
    except Exception:
        return True


def verify_password(password_hash: str | None, password: str) -> bool:
    plain = password or ""
    if not password_hash:
        try:
            _PASSWORD_HASHER.verify(_DUMMY_PASSWORD_HASH, plain)
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            pass
        return False
    if _is_argon2_hash(password_hash):
        try:
            return bool(_PASSWORD_HASHER.verify(password_hash, plain))
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            return False
    # Legacy Werkzeug hashes (scrypt / pbkdf2).
    return bool(check_password_hash(password_hash, plain))


def verify_password_for_row(row, password: str) -> bool:
    if not row:
        return verify_password(None, password)
    return verify_password(row["password_hash"], password)


def upgrade_password_hash_if_needed(conn, user_id: int, password: str, password_hash: str | None) -> bool:
    """Rewrite password_hash to Argon2id when the stored encoding is legacy or outdated.

    Returns True when the row was updated.
    """
    if not user_id or not password_needs_rehash(password_hash):
        return False
    new_hash = hash_password(password)
    conn.execute(
        """
        UPDATE users
           SET password_hash = ?,
               updated_at = ?
         WHERE id = ?
        """,
        (new_hash, sql_now(), int(user_id)),
    )
    return True


def clear_login_failures(conn, user_id: int) -> None:
    conn.execute(
        """
        UPDATE users
           SET failed_login_attempts = 0,
               captcha_required = 0,
               locked_at = NULL,
               unlock_token_hash = NULL,
               unlock_token_expires_at = NULL,
               updated_at = ?
         WHERE id = ?
        """,
        (sql_now(), user_id),
    )


def admin_unlock_user(conn, user_id: int) -> None:
    clear_login_failures(conn, user_id)


def _hash_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def issue_unlock_token(conn, user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now() + timedelta(hours=UNLOCK_TOKEN_TTL_HOURS)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    conn.execute(
        """
        UPDATE users
           SET unlock_token_hash = ?,
               unlock_token_expires_at = ?,
               updated_at = ?
         WHERE id = ?
        """,
        (_hash_token(token), expires, sql_now(), user_id),
    )
    return token


def verify_and_consume_unlock_token(conn, token: str):
    """Return unlocked user row id on success, else None."""
    token = (token or "").strip()
    if not token:
        return None
    token_hash = _hash_token(token)
    row = conn.execute(
        """
        SELECT id, unlock_token_expires_at
          FROM users
         WHERE unlock_token_hash = ?
        """,
        (token_hash,),
    ).fetchone()
    if not row:
        return None
    expires_raw = row["unlock_token_expires_at"] or ""
    try:
        expires_at = datetime.strptime(expires_raw, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if expires_at < datetime.now():
        return None
    clear_login_failures(conn, int(row["id"]))
    return int(row["id"])


def record_failed_login(conn, user_id: int) -> dict:
    """
    Increment failure counters. Returns updated state:
    {attempts, captcha_required, locked, newly_locked}
    """
    row = conn.execute(
        "SELECT failed_login_attempts, captcha_required, locked_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return {
            "attempts": 0,
            "captcha_required": False,
            "locked": False,
            "newly_locked": False,
        }

    was_locked = bool(row["locked_at"])
    attempts = int(row["failed_login_attempts"] or 0) + 1
    captcha_required = 1 if attempts >= CAPTCHA_AFTER_FAILURES else 0
    newly_locked = False
    locked_at = row["locked_at"]
    if attempts >= LOCK_AFTER_FAILURES and not was_locked:
        locked_at = sql_now()
        newly_locked = True
        captcha_required = 0

    conn.execute(
        """
        UPDATE users
           SET failed_login_attempts = ?,
               captcha_required = ?,
               locked_at = ?,
               updated_at = ?
         WHERE id = ?
        """,
        (attempts, captcha_required, locked_at, sql_now(), user_id),
    )
    return {
        "attempts": attempts,
        "captcha_required": bool(captcha_required) and not bool(locked_at),
        "locked": bool(locked_at),
        "newly_locked": newly_locked,
    }


def record_unknown_user_failure() -> None:
    """Burn time for unknown usernames (dummy hash check already done by caller)."""
    return None


# ── IP throttle ──────────────────────────────────────────────────────────────

def client_ip_from_request(request) -> str:
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return (request.remote_addr or "unknown").strip() or "unknown"


def note_ip_login_attempt(ip: str) -> None:
    now = time.time()
    cutoff = now - IP_THROTTLE_WINDOW_SEC
    with _ip_lock:
        stamps = [t for t in _ip_attempts.get(ip, []) if t >= cutoff]
        stamps.append(now)
        _ip_attempts[ip] = stamps


def ip_is_throttled(ip: str) -> bool:
    now = time.time()
    cutoff = now - IP_THROTTLE_WINDOW_SEC
    with _ip_lock:
        stamps = [t for t in _ip_attempts.get(ip, []) if t >= cutoff]
        _ip_attempts[ip] = stamps
        return len(stamps) >= IP_THROTTLE_LIMIT


def reset_ip_throttle_for_tests() -> None:
    with _ip_lock:
        _ip_attempts.clear()


# ── CAPTCHA ──────────────────────────────────────────────────────────────────

def _captcha_alphabet() -> str:
    # Avoid ambiguous glyphs.
    return "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_captcha_text(length: int = 5) -> str:
    alphabet = _captcha_alphabet()
    return "".join(secrets.choice(alphabet) for _ in range(length))


def store_captcha_challenge(session, answer: str) -> None:
    session[CAPTCHA_SESSION_ANSWER] = (answer or "").strip().upper()
    session[CAPTCHA_SESSION_EXPIRES] = int(time.time()) + CAPTCHA_TTL_SEC


def clear_captcha_challenge(session) -> None:
    session.pop(CAPTCHA_SESSION_ANSWER, None)
    session.pop(CAPTCHA_SESSION_EXPIRES, None)


def verify_captcha_answer(session, submitted: str) -> bool:
    expected = (session.get(CAPTCHA_SESSION_ANSWER) or "").strip().upper()
    expires = int(session.get(CAPTCHA_SESSION_EXPIRES) or 0)
    clear_captcha_challenge(session)
    if not expected or expires < int(time.time()):
        return False
    got = (submitted or "").strip().upper()
    return hmac.compare_digest(expected, got)


def render_captcha_png(text: str) -> bytes:
    """Render a simple distorted CAPTCHA image. Requires Pillow."""
    try:
        from PIL import Image, ImageDraw, ImageFont, ImageFilter
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Pillow is required for login CAPTCHA") from exc

    width, height = 160, 56
    img = Image.new("RGB", (width, height), (239, 246, 255))
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("Arial.ttf", 28)
    except OSError:
        font = ImageFont.load_default()

    for _ in range(8):
        x1, y1 = random.randint(0, width), random.randint(0, height)
        x2, y2 = random.randint(0, width), random.randint(0, height)
        draw.line((x1, y1, x2, y2), fill=(147, 197, 253), width=1)

    x = 14
    for ch in text:
        y = random.randint(8, 18)
        draw.text((x, y), ch, font=font, fill=(30, 64, 175))
        x += 26 + random.randint(-2, 4)

    for _ in range(40):
        draw.point(
            (random.randint(0, width - 1), random.randint(0, height - 1)),
            fill=(96, 165, 250),
        )

    img = img.filter(ImageFilter.SMOOTH)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def is_valid_email(value: str) -> bool:
    value = (value or "").strip()
    if not value or len(value) > 254 or " " in value:
        return False
    if value.count("@") != 1:
        return False
    local, _, domain = value.partition("@")
    if not local or not domain or "." not in domain:
        return False
    return True
