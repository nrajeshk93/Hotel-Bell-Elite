#!/usr/bin/env python3
"""Copy a built Kivy APK into static/mobile and write version.json.

Phones pull this file from Flask after you git-push and AWS syncs.

Usage (from repo root):
  .venv/bin/python scripts/publish_mobile_apk.py
  .venv/bin/python scripts/publish_mobile_apk.py --apk mobile_kivy/bin/hbemobile-0.2.0-arm64-v8a-release.apk

Then:
  git add static/mobile/hbemobile.apk static/mobile/version.json mobile_kivy/
  git push
  (AWS sync as usual)

Reuse the SAME keystore for every Android build. Debug and release keys
cannot update each other. The first APK that contains the updater must be
installed by hand once; later publishes auto-update.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "mobile_kivy" / "buildozer.spec"
BIN_DIR = ROOT / "mobile_kivy" / "bin"
DEST_DIR = ROOT / "static" / "mobile"
DEST_APK = DEST_DIR / "hbemobile.apk"
DEST_MANIFEST = DEST_DIR / "version.json"
APK_URL_PATH = "/api/mobile/hbemobile.apk"


def parse_buildozer_spec(path: Path) -> tuple[str, int]:
    text = path.read_text(encoding="utf-8")
    version_match = re.search(r"(?m)^version\s*=\s*(\S+)", text)
    code_match = re.search(r"(?m)^android\.numeric_version\s*=\s*(\d+)", text)
    if not version_match:
        raise SystemExit(f"Could not read version from {path}")
    version = version_match.group(1).strip()
    version_code = int(code_match.group(1)) if code_match else 1
    return version, version_code


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_default_apk() -> Path:
    if not BIN_DIR.is_dir():
        raise SystemExit(
            f"No APK directory {BIN_DIR}. Build first: cd mobile_kivy && buildozer android release"
        )
    apks = sorted(BIN_DIR.glob("*.apk"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not apks:
        raise SystemExit(f"No .apk files in {BIN_DIR}")
    return apks[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apk",
        default="",
        help="Built APK path (default: newest mobile_kivy/bin/*.apk)",
    )
    parser.add_argument(
        "--spec",
        default=str(SPEC_PATH),
        help="buildozer.spec to read version / versionCode from",
    )
    parser.add_argument(
        "--dest-dir",
        default=str(DEST_DIR),
        help="Directory for hbemobile.apk + version.json (default: static/mobile)",
    )
    args = parser.parse_args(argv)

    spec_path = Path(os.path.abspath(os.path.expanduser(args.spec)))
    version, version_code = parse_buildozer_spec(spec_path)
    apk_src = Path(os.path.abspath(os.path.expanduser(args.apk))) if args.apk else find_default_apk()
    if not apk_src.is_file():
        print(f"APK not found: {apk_src}", file=sys.stderr)
        return 1

    dest_dir = Path(os.path.abspath(os.path.expanduser(args.dest_dir)))
    dest_apk = dest_dir / "hbemobile.apk"
    dest_manifest = dest_dir / "version.json"
    dest_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(apk_src, dest_apk)
    digest = sha256_file(dest_apk)
    manifest = {
        "version": version,
        "versionCode": version_code,
        "apk_url": APK_URL_PATH,
        "sha256": digest,
        "force": False,
    }
    dest_manifest.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Copied {apk_src} -> {dest_apk}")
    print(f"Wrote {dest_manifest}")
    print(json.dumps(manifest, indent=2))
    print()
    print("Next: git add static/mobile/hbemobile.apk static/mobile/version.json (plus source), then push.")
    print("Reuse the same keystore. First updater APK is a manual install; later ones self-update.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
