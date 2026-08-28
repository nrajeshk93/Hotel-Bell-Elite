"""Load a stable Flask SECRET_KEY without a public default."""

from __future__ import annotations

import os
import secrets
import stat

PUBLIC_DEFAULT_SECRET_KEY = "hotel-bell-elite-dev-key-change-in-production"

_ROOT = os.path.dirname(os.path.abspath(__file__))
_INSTANCE_DIR = os.path.join(_ROOT, "instance")
_SECRET_FILE = os.path.join(_INSTANCE_DIR, "secret_key")


def _usable(value: str | None) -> str:
    text = (value or "").strip()
    if not text or text == PUBLIC_DEFAULT_SECRET_KEY:
        return ""
    return text


def _read_secret_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return _usable(fh.read())
    except OSError:
        return ""


def _write_secret_file(path: str, value: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(value)
    except OSError:
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def get_secret_key(secret_file: str | None = None) -> str:
    """Return SECRET_KEY from env, else a persisted instance file, else generate one.

    Never falls back to the public development default.
    """
    env_key = _usable(os.environ.get("SECRET_KEY"))
    if env_key:
        return env_key

    path = secret_file or _SECRET_FILE
    saved = _read_secret_file(path)
    if saved:
        os.environ["SECRET_KEY"] = saved
        return saved

    generated = secrets.token_urlsafe(48)
    _write_secret_file(path, generated)
    # Another process may have won the create race.
    saved = _read_secret_file(path) or generated
    os.environ["SECRET_KEY"] = saved
    return saved
