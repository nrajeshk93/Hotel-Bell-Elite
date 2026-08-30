"""Runtime configuration for the mobile client."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Desktop / local `python main.py`.
DESKTOP_API_BASE_URL = "http://127.0.0.1:8002"
# Sideloaded / installed Android APK always targets production by default.
# Override only via settings.json or HBE_API_BASE_URL when needed for local testing.
ANDROID_RELEASE_API_BASE_URL = "https://belleliteaccounts.com"
# Kept for back-compat / explicit local overrides — not used as the Android default.
ANDROID_DEBUG_API_BASE_URL = ANDROID_RELEASE_API_BASE_URL

# Back-compat alias used as the desktop default.
DEFAULT_API_BASE_URL = DESKTOP_API_BASE_URL
REQUEST_TIMEOUT_S = float(os.environ.get("HBE_API_TIMEOUT", "30"))

CSRF_COOKIE = "hbe_csrf"
CSRF_HEADER = "X-CSRFToken"
SESSION_HINT_COOKIE = "session"

_DEFAULT_CONFIG_DIR = Path.home() / ".hbe_mobile"


def config_dir() -> Path:
    return Path(os.environ.get("HBE_MOBILE_CONFIG_DIR", _DEFAULT_CONFIG_DIR))


def config_file() -> Path:
    return config_dir() / "settings.json"


def is_android() -> bool:
    """True when running inside a python-for-android APK.

    Avoid importing Kivy here so desktop unit tests stay window-free.
    """
    if os.environ.get("ANDROID_ARGUMENT"):
        return True
    return sys.platform == "android"


def is_android_debuggable() -> bool | None:
    """FLAG_DEBUGGABLE via pyjnius. None if not Android or pyjnius failed."""
    if not is_android():
        return None
    try:
        from jnius import autoclass

        info_cls = autoclass("android.content.pm.ApplicationInfo")
        flag = int(info_cls.FLAG_DEBUGGABLE)
        activity = None
        for activity_name in (
            "org.kivy.android.PythonActivity",
            "org.renpy.android.PythonActivity",
        ):
            try:
                activity_cls = autoclass(activity_name)
                activity = activity_cls.mActivity
                if activity is not None:
                    break
            except Exception:
                activity = None
        if activity is None:
            return None
        app_info = activity.getApplicationInfo()
        return bool(int(app_info.flags) & flag)
    except Exception:
        return None


def default_api_base_url() -> str:
    """Platform default when settings.json and HBE_API_BASE_URL are unset.

    Android APKs (debug and release) default to production so hotel phones
    never hit localhost. Desktop `python main.py` still uses local Flask.
    """
    if is_android():
        return ANDROID_RELEASE_API_BASE_URL
    return DESKTOP_API_BASE_URL


def load_settings() -> dict:
    path = config_file()
    fallback = {"api_base_url": default_api_base_url()}
    if not path.is_file():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return fallback
        data.setdefault("api_base_url", fallback["api_base_url"])
        return data
    except (OSError, json.JSONDecodeError):
        return fallback


def save_settings(settings: dict) -> None:
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "settings.json").write_text(json.dumps(settings, indent=2), encoding="utf-8")


def _explicit_settings_url() -> str | None:
    """settings.json wins when the user (or a previous save) set api_base_url."""
    path = config_file()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        url = str(data.get("api_base_url") or "").strip().rstrip("/")
        return url or None
    except (OSError, json.JSONDecodeError):
        return None


def get_api_base_url() -> str:
    explicit = _explicit_settings_url()
    if explicit:
        return explicit
    env = (os.environ.get("HBE_API_BASE_URL") or "").strip().rstrip("/")
    if env:
        return env
    return default_api_base_url()


def set_api_base_url(url: str) -> None:
    settings = load_settings()
    settings["api_base_url"] = (url or default_api_base_url()).rstrip("/")
    save_settings(settings)


def httpx_verify():
    """CA bundle for httpx. Never returns False."""
    try:
        import certifi

        path = certifi.where()
        if path:
            return path
    except Exception:
        pass
    return True
