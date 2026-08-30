"""Background silent self-update for the sideloaded Android APK.

Desktop / pygame: no-op. Failures are logged and retried; they never affect
POS, login, or other screens. There is no in-app "Update now?" dialog.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin

import httpx

from hbe_mobile import config
from hbe_mobile.update_check import (
    ANDROID_PACKAGE,
    is_allowed_android_ota_origin,
    is_remote_newer,
    is_same_origin_url,
    parse_manifest,
    resolve_apk_url,
    sha256_matches,
)
from hbe_mobile.version import APP_VERSION, APP_VERSION_CODE

log = logging.getLogger("hbe.ota")

CHECK_INTERVAL_S = 45 * 60
MANIFEST_PATH = "/api/mobile/version"
MAX_APK_BYTES = 150 * 1024 * 1024
MAX_REDIRECTS = 5
_lock = threading.Lock()
_started = False


def _android_activity():
    try:
        from jnius import autoclass
    except Exception:
        return None
    for name in (
        "org.kivy.android.PythonActivity",
        "org.renpy.android.PythonActivity",
    ):
        try:
            activity = autoclass(name).mActivity
            if activity is not None:
                return activity
        except Exception:
            continue
    return None


def installed_version() -> tuple[str, int]:
    """Prefer PackageManager (matches the APK); fall back to version.py."""
    activity = _android_activity()
    if activity is not None:
        try:
            info = activity.getPackageManager().getPackageInfo(activity.getPackageName(), 0)
            name = str(info.versionName or APP_VERSION)
            try:
                code = int(info.getLongVersionCode())
            except Exception:
                code = int(info.versionCode)
            return name, code
        except Exception:
            log.exception("HBE OTA: PackageManager version lookup failed")
    return APP_VERSION, APP_VERSION_CODE


def _cache_apk_path() -> Path:
    activity = _android_activity()
    if activity is not None:
        try:
            cache = activity.getCacheDir().getAbsolutePath()
            return Path(cache) / "hbemobile-update.apk"
        except Exception:
            pass
    dest_dir = config.config_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    return dest_dir / "hbemobile-update.apk"


def _http_client() -> httpx.Client:
    kwargs = {
        "timeout": httpx.Timeout(60.0, connect=20.0),
        "follow_redirects": False,
        "headers": {"User-Agent": f"HBE-Mobile-OTA/{APP_VERSION}", "Cache-Control": "no-cache"},
        "verify": config.httpx_verify(),
    }
    return httpx.Client(**kwargs)


def _follow_same_origin(base_url: str, current: str, location: str) -> str | None:
    nxt = urljoin(current, location or "")
    if not is_same_origin_url(base_url, nxt):
        return None
    return nxt


def fetch_manifest(base_url: str) -> dict:
    url = base_url.rstrip("/") + MANIFEST_PATH
    current = url
    with _http_client() as client:
        for _ in range(MAX_REDIRECTS):
            response = client.get(current)
            if response.status_code in (301, 302, 303, 307, 308):
                nxt = _follow_same_origin(
                    base_url, current, response.headers.get("location") or ""
                )
                if not nxt:
                    response.raise_for_status()
                    raise httpx.HTTPError("manifest redirect left API host")
                current = nxt
                continue
            response.raise_for_status()
            return parse_manifest(response.json())
    raise httpx.HTTPError("too many manifest redirects")


def download_apk(url: str, dest: Path, *, origin_base: str) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".apk.part")
    if not is_same_origin_url(origin_base, url):
        raise ValueError("apk url is not on the API host")
    current = url
    with _http_client() as client:
        for _ in range(MAX_REDIRECTS):
            with client.stream("GET", current) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    nxt = _follow_same_origin(
                        origin_base, current, response.headers.get("location") or ""
                    )
                    if not nxt:
                        raise ValueError("apk redirect left the API host")
                    current = nxt
                    continue
                response.raise_for_status()
                written = 0
                with tmp.open("wb") as handle:
                    for chunk in response.iter_bytes(1024 * 64):
                        written += len(chunk)
                        if written > MAX_APK_BYTES:
                            raise ValueError("apk exceeds size limit")
                        handle.write(chunk)
                break
        else:
            raise ValueError("too many apk redirects")
    tmp.replace(dest)
    return dest


def _apk_package_name(apk_path: Path) -> str:
    try:
        from jnius import autoclass

        activity = _android_activity()
        if activity is None:
            return ""
        helper = autoclass("com.hotelbellelite.hbemobile.SilentUpdateHelper")
        return str(helper.apkPackageName(activity, str(apk_path)) or "")
    except Exception:
        log.exception("HBE OTA: apk package probe failed")
        return ""


def _silent_install(apk_path: Path) -> str:
    """Ask the Java helper to session-install. Never raises."""
    try:
        from jnius import autoclass

        activity = _android_activity()
        if activity is None:
            return "no_activity"
        helper = autoclass("com.hotelbellelite.hbemobile.SilentUpdateHelper")
        result = helper.installApk(activity, str(apk_path))
        return str(result or "")
    except Exception:
        log.exception("HBE OTA: PackageInstaller helper failed")
        return "helper_missing"


def check_and_apply_update() -> None:
    """Download + silent-install if the server has a newer signed APK."""
    if not config.is_android():
        return
    if not _lock.acquire(blocking=False):
        return
    try:
        local_version, local_code = installed_version()
        base = config.get_api_base_url()
        if not is_allowed_android_ota_origin(base):
            log.error("HBE OTA: refusing non-HTTPS API origin on Android")
            return
        manifest = fetch_manifest(base)
        if not is_remote_newer(
            local_version=local_version,
            local_version_code=local_code,
            remote_version=manifest["version"],
            remote_version_code=manifest["versionCode"],
        ):
            log.info(
                "HBE OTA: up to date local=%s/%s remote=%s/%s",
                local_version,
                local_code,
                manifest["version"],
                manifest["versionCode"],
            )
            return
        if not manifest["sha256"]:
            log.warning("HBE OTA: manifest missing sha256, skip")
            return
        apk_url = resolve_apk_url(base, manifest["apk_url"])
        if not is_same_origin_url(base, apk_url):
            log.error("HBE OTA: refusing off-host apk url")
            return
        dest = _cache_apk_path()
        log.info("HBE OTA: downloading %s", apk_url)
        download_apk(apk_url, dest, origin_base=base)
        if not sha256_matches(str(dest), manifest["sha256"]):
            log.error("HBE OTA: sha256 mismatch, deleting download")
            try:
                dest.unlink()
            except OSError:
                pass
            return
        pkg = _apk_package_name(dest)
        if pkg != ANDROID_PACKAGE:
            log.error("HBE OTA: package mismatch got=%s, deleting download", pkg)
            try:
                dest.unlink()
            except OSError:
                pass
            return
        result = _silent_install(dest)
        log.info("HBE OTA: install result=%s", result)
    except Exception:
        log.exception("HBE OTA: check failed (POS/login unaffected)")
    finally:
        _lock.release()


def _spawn_check(*_args) -> None:
    threading.Thread(target=check_and_apply_update, name="hbe-ota", daemon=True).start()


def request_update_check(*, delay_s: float = 0.5) -> None:
    """Kick an OTA check soon (login / resume). Safe to call often; lock dedupes."""
    if not config.is_android():
        return
    try:
        from kivy.clock import Clock
    except Exception:
        _spawn_check()
        return
    Clock.schedule_once(_spawn_check, max(0.0, float(delay_s or 0)))


def start_background_updater(_app: Optional[object] = None) -> None:
    """Schedule a check after UI is up, then every 45 minutes. Desktop no-op."""
    global _started
    if not config.is_android():
        return
    if _started:
        return
    try:
        from kivy.clock import Clock
    except Exception:
        return
    _started = True
    Clock.schedule_once(_spawn_check, 0)
    Clock.schedule_interval(_spawn_check, CHECK_INTERVAL_S)

    # Also re-check when the app returns to foreground (after AWS published a build).
    try:
        from kivy.core.window import Window

        def _on_restore(*_a):
            request_update_check(delay_s=1.0)

        Window.bind(on_restore=_on_restore)
    except Exception:
        log.exception("HBE OTA: could not bind Window.on_restore")
