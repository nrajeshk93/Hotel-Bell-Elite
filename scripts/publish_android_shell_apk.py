#!/usr/bin/env python3
"""Publish the WebView Android shell APK for silent OTA.

Copies Hotel-Bell-Elite.apk → static/mobile/hbe.apk and writes
static/mobile/hbe_shell_version.json from android/app/build.gradle.kts.

Usage (from repo root):
  ./mobile_kivy/build_apk_fast.sh
  .venv/bin/python scripts/publish_android_shell_apk.py
  git add static/mobile/hbe.apk static/mobile/hbe_shell_version.json
  git push
  # then AWS Server sync

Phones already on 1.0.2+ pull /api/mobile/shell/version and self-install.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADLE = ROOT / "android" / "app" / "build.gradle.kts"
BIN_APK = ROOT / "mobile_kivy" / "bin" / "Hotel-Bell-Elite.apk"
DEST_DIR = ROOT / "static" / "mobile"
DEST_APK = DEST_DIR / "hbe.apk"
DEST_MANIFEST = DEST_DIR / "hbe_shell_version.json"
APK_URL_PATH = "/api/mobile/hbe.apk"


def parse_gradle_versions(path: Path) -> tuple[str, int]:
    text = path.read_text(encoding="utf-8")
    version_match = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    code_match = re.search(r"versionCode\s*=\s*(\d+)", text)
    if not version_match or not code_match:
        raise SystemExit(f"Could not read versionName/versionCode from {path}")
    return version_match.group(1).strip(), int(code_match.group(1))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apk",
        default="",
        help="Built APK path (default: mobile_kivy/bin/Hotel-Bell-Elite.apk)",
    )
    args = parser.parse_args(argv)
    apk = Path(args.apk) if args.apk else BIN_APK
    if not apk.is_file():
        raise SystemExit(
            f"Missing APK {apk}. Build first: ./mobile_kivy/build_apk_fast.sh"
        )
    if not GRADLE.is_file():
        raise SystemExit(f"Missing {GRADLE}")

    version, version_code = parse_gradle_versions(GRADLE)
    DEST_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(apk, DEST_APK)
    digest = sha256_file(DEST_APK)
    payload = {
        "version": version,
        "versionCode": version_code,
        "apk_url": APK_URL_PATH,
        "sha256": digest,
        "force": False,
        "package": "com.hotelbellelite.hbe",
    }
    DEST_MANIFEST.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Published {DEST_APK} ({DEST_APK.stat().st_size} bytes)")
    print(f"Manifest {DEST_MANIFEST}")
    print(f"  version={version} versionCode={version_code}")
    print(f"  sha256={digest}")
    print("Next: git add static/mobile/hbe.apk static/mobile/hbe_shell_version.json && git push && AWS sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
