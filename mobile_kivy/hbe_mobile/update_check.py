"""Pure helpers for mobile OTA version compare / manifest parsing.

No Kivy, no pyjnius — safe for unit tests and desktop.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

_NON_DIGIT = re.compile(r"[^\d]+")

ANDROID_PACKAGE = "com.hotelbellelite.hbemobile"
DEFAULT_APK_RELATIVE = "api/mobile/hbemobile.apk"
# HTTP is only for explicit local/dev hosts — never the Android production default.
_ANDROID_OTA_HTTP_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "10.0.2.2"})


def version_tuple(value: str) -> tuple[int, ...]:
    parts = [int(p) for p in _NON_DIGIT.split(str(value or "").strip()) if p]
    return tuple(parts) or (0,)


def is_remote_newer(
    *,
    local_version: str,
    local_version_code: int,
    remote_version: str,
    remote_version_code: Any = None,
) -> bool:
    """True when the published APK should replace the installed one.

    versionCode is the primary comparison (Android PackageInstaller). When
    codes are equal or the remote code is missing, fall back to the dotted
    version string. Never treats an equal or older build as an update.
    """
    local_code = int(local_version_code or 0)
    remote_code: Optional[int]
    try:
        if remote_version_code is None or remote_version_code == "":
            remote_code = None
        else:
            remote_code = int(remote_version_code)
    except (TypeError, ValueError):
        remote_code = None
    if remote_code is not None and remote_code != local_code:
        return remote_code > local_code
    return version_tuple(remote_version) > version_tuple(local_version)


def parse_manifest(payload: Any) -> dict:
    data = payload if isinstance(payload, dict) else {}
    try:
        version_code = int(data.get("versionCode") if data.get("versionCode") is not None else data.get("version_code") or 0)
    except (TypeError, ValueError):
        version_code = 0
    sha256 = str(data.get("sha256") or data.get("sha256sum") or "").strip().lower()
    return {
        "version": str(data.get("version") or "").strip(),
        "versionCode": version_code,
        "apk_url": str(data.get("apk_url") or data.get("apkUrl") or "").strip(),
        "sha256": sha256,
        "force": bool(data.get("force")),
    }


def _default_port(scheme: str) -> int | None:
    if scheme == "https":
        return 443
    if scheme == "http":
        return 80
    return None


def is_same_origin_url(base_url: str, candidate: str) -> bool:
    """True when candidate is http(s) on the same host+port as base_url.

    HTTPS bases cannot be downgraded to HTTP. Absolute URLs on other hosts,
    protocol-relative //host URLs, and empty values are rejected.
    """
    base = urlparse((base_url or "").strip())
    got = urlparse((candidate or "").strip())
    if got.scheme not in ("http", "https"):
        return False
    if not got.hostname or not base.hostname:
        return False
    if got.hostname.lower() != base.hostname.lower():
        return False
    base_port = base.port or _default_port((base.scheme or "").lower())
    got_port = got.port or _default_port(got.scheme)
    if base_port != got_port:
        return False
    if (base.scheme or "").lower() == "https" and got.scheme != "https":
        return False
    return True


def resolve_apk_url(base_url: str, apk_url: str) -> str:
    """Resolve apk_url against the API origin. Off-host values fall back."""
    base = (base_url or "").rstrip("/") + "/"
    default = urljoin(base, DEFAULT_APK_RELATIVE)
    url = (apk_url or "").strip()
    if not url:
        return default
    resolved = urljoin(base, url)
    if not is_same_origin_url(base_url, resolved):
        return default
    return resolved




def is_allowed_android_ota_origin(base_url: str) -> bool:
    """Android silent OTA: HTTPS required, except explicit localhost/dev HTTP."""
    parsed = urlparse((base_url or "").strip())
    scheme = (parsed.scheme or "").lower()
    host = (parsed.hostname or "").lower()
    if not host:
        return False
    if scheme == "https":
        return True
    if scheme == "http" and host in _ANDROID_OTA_HTTP_HOSTS:
        return True
    return False


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_matches(path: str, expected: str) -> bool:
    want = (expected or "").strip().lower()
    if not want:
        return False
    return sha256_file(path) == want
