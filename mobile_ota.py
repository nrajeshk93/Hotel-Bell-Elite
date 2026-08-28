"""Public mobile APK / version manifest for sideloaded Kivy phones.

Phones pull updates; AWS cannot push. Routes are registered from app.py and
must stay login-free (see workspace_access._PUBLIC_ENDPOINTS).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from flask import jsonify, send_file

ROOT = Path(__file__).resolve().parent
MOBILE_DIR = ROOT / "static" / "mobile"
MANIFEST_NAME = "version.json"
APK_NAME = "hbemobile.apk"

# Fallback when version.json has not been published yet (must match the
# first sideloaded client so 0.1.0 phones do not try to update).
DEFAULT_VERSION = "0.1.0"
DEFAULT_VERSION_CODE = 1

_NO_CACHE = "no-store, no-cache, must-revalidate, private, max-age=0"


def apk_path() -> Path:
    return MOBILE_DIR / APK_NAME


def manifest_path() -> Path:
    return MOBILE_DIR / MANIFEST_NAME


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_manifest() -> dict:
    """Return the published manifest dict (never raises)."""
    payload = {
        "version": DEFAULT_VERSION,
        "versionCode": DEFAULT_VERSION_CODE,
        "apk_url": f"/api/mobile/{APK_NAME}",
        "sha256": "",
        "force": False,
        "apk_available": False,
    }
    path = manifest_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                payload.update(data)
        except (OSError, json.JSONDecodeError):
            pass
    apk = apk_path()
    apk_available = apk.is_file()
    payload["apk_available"] = apk_available
    if not payload.get("sha256") and apk_available:
        try:
            payload["sha256"] = sha256_file(apk)
        except OSError:
            pass
    payload["apk_url"] = str(payload.get("apk_url") or f"/api/mobile/{APK_NAME}")
    try:
        payload["versionCode"] = int(payload.get("versionCode") or DEFAULT_VERSION_CODE)
    except (TypeError, ValueError):
        payload["versionCode"] = DEFAULT_VERSION_CODE
    payload["version"] = str(payload.get("version") or DEFAULT_VERSION)
    payload["force"] = bool(payload.get("force"))
    payload["sha256"] = str(payload.get("sha256") or "")
    return payload


def _nocache(response):
    """Prevent browsers / Cloudflare / nginx from caching OTA payloads."""
    response.headers["Cache-Control"] = _NO_CACHE
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    response.headers["Surrogate-Control"] = "no-store"
    response.headers["CDN-Cache-Control"] = "no-store"
    # Avoid cookie-based caches treating the public OTA URL as a session page.
    response.headers["Vary"] = "Accept"
    return response


def manifest_response():
    response = jsonify(load_manifest())
    return _nocache(response)


def apk_response():
    path = apk_path()
    if not path.is_file():
        return _nocache(jsonify({"ok": False, "error": "APK not published yet."})), 404
    response = send_file(
        path,
        mimetype="application/vnd.android.package-archive",
        as_attachment=True,
        download_name=APK_NAME,
        max_age=0,
        conditional=False,
        etag=False,
    )
    return _nocache(response)
