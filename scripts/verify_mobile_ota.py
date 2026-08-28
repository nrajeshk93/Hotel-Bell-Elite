#!/usr/bin/env python3
"""Verify mobile OTA endpoints are public and cache-safe.

Usage:
  .venv/bin/python scripts/verify_mobile_ota.py
  .venv/bin/python scripts/verify_mobile_ota.py --base https://belleliteaccounts.com
  .venv/bin/python scripts/verify_mobile_ota.py --base http://127.0.0.1:8002
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get(url: str) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "HBE-OTA-Verify/1.0",
            "Accept": "application/json,application/vnd.android.package-archive,*/*",
            "Cache-Control": "no-cache",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            headers = {k.lower(): v for k, v in resp.headers.items()}
            return int(resp.status), headers, resp.read()
    except urllib.error.HTTPError as err:
        headers = {k.lower(): v for k, v in (err.headers.items() if err.headers else [])}
        return int(err.code), headers, err.read() or b""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base",
        default="https://belleliteaccounts.com",
        help="Site origin (default: production)",
    )
    args = parser.parse_args(argv)
    base = args.base.rstrip("/")
    errors: list[str] = []

    version_url = f"{base}/api/mobile/version"
    status, headers, body = _get(version_url)
    print(f"GET {version_url}")
    print(f"  status: {status}")
    print(f"  cache-control: {headers.get('cache-control', '')}")
    print(f"  content-type: {headers.get('content-type', '')}")
    loc = headers.get("location", "")
    if loc:
        print(f"  location: {loc}")
        errors.append("version endpoint redirected (must stay login-free)")
    if status != 200:
        errors.append(f"version HTTP {status}")
    else:
        ctype = (headers.get("content-type") or "").lower()
        if "json" not in ctype:
            preview = body[:120].decode("utf-8", errors="replace")
            errors.append(f"version returned non-JSON ({ctype}): {preview!r}")
        else:
            try:
                data = json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                errors.append("version body is not valid JSON")
                data = {}
            print(f"  body: {json.dumps(data, indent=2)[:500]}")
            if not isinstance(data, dict):
                errors.append("version JSON must be an object")
            else:
                if "versionCode" not in data:
                    errors.append("missing versionCode")
                if not data.get("apk_url"):
                    errors.append("missing apk_url")
                sha = str(data.get("sha256") or "")
                available = bool(data.get("apk_available"))
                if available and not sha:
                    errors.append("apk_available but sha256 empty")
                if not available:
                    print("  note: APK not published yet (apk_available=false) — expected until publish_mobile_apk.py")
        cache = (headers.get("cache-control") or "").lower()
        if "no-store" not in cache and "no-cache" not in cache:
            errors.append("version Cache-Control should include no-store or no-cache")

    apk_url = f"{base}/api/mobile/hbemobile.apk"
    status, headers, body = _get(apk_url)
    print(f"GET {apk_url}")
    print(f"  status: {status}")
    print(f"  content-type: {headers.get('content-type', '')}")
    if headers.get("location"):
        errors.append("APK endpoint redirected (must stay login-free)")
    if status == 404:
        print("  note: APK missing (404) — publish with scripts/publish_mobile_apk.py then AWS sync")
    elif status != 200:
        errors.append(f"APK HTTP {status}")
    else:
        ctype = (headers.get("content-type") or "").lower()
        if "html" in ctype:
            errors.append("APK endpoint returned HTML (login page?)")
        elif "android.package-archive" not in ctype and "octet-stream" not in ctype:
            errors.append(f"unexpected APK content-type: {ctype}")
        print(f"  bytes: {len(body)}")

    if errors:
        print("\nFAIL:")
        for item in errors:
            print(f"  - {item}")
        return 1
    print("\nOK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
