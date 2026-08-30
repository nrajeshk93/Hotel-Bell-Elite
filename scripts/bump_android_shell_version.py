#!/usr/bin/env python3
"""Bump WebView Android shell version in android/app/build.gradle.kts.

Phones compare this versionCode to /api/mobile/shell/version.

Usage (from repo root):
  .venv/bin/python scripts/bump_android_shell_version.py
  .venv/bin/python scripts/bump_android_shell_version.py --minor
  .venv/bin/python scripts/bump_android_shell_version.py --set 1.0.4 --code 5
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GRADLE = ROOT / "android" / "app" / "build.gradle.kts"


def read_current() -> tuple[str, int]:
    text = GRADLE.read_text(encoding="utf-8")
    version_match = re.search(r'versionName\s*=\s*"([^"]+)"', text)
    code_match = re.search(r"versionCode\s*=\s*(\d+)", text)
    if not version_match or not code_match:
        raise SystemExit(f"Could not read versionName/versionCode from {GRADLE}")
    return version_match.group(1).strip(), int(code_match.group(1))


def bump_semver(version: str, *, part: str) -> str:
    bits = [int(p) for p in re.split(r"[^\d]+", version) if p]
    while len(bits) < 3:
        bits.append(0)
    major, minor, patch = bits[0], bits[1], bits[2]
    if part == "major":
        major, minor, patch = major + 1, 0, 0
    elif part == "minor":
        minor, patch = minor + 1, 0
    else:
        patch += 1
    return f"{major}.{minor}.{patch}"


def write_gradle(version: str, code: int) -> None:
    text = GRADLE.read_text(encoding="utf-8")
    text, n1 = re.subn(r'versionName\s*=\s*"[^"]+"', f'versionName = "{version}"', text, count=1)
    text, n2 = re.subn(r"versionCode\s*=\s*\d+", f"versionCode = {code}", text, count=1)
    if n1 != 1 or n2 != 1:
        raise SystemExit(f"Failed to rewrite versionName/versionCode in {GRADLE}")
    GRADLE.write_text(text, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--patch", action="store_true", help="Bump patch (default)")
    group.add_argument("--minor", action="store_true", help="Bump minor")
    group.add_argument("--major", action="store_true", help="Bump major")
    parser.add_argument("--set", dest="set_version", default="", help="Set exact version string")
    parser.add_argument("--code", type=int, default=0, help="Set exact versionCode (default: +1)")
    args = parser.parse_args(argv)

    current_version, current_code = read_current()
    if args.set_version:
        new_version = args.set_version.strip()
    elif args.major:
        new_version = bump_semver(current_version, part="major")
    elif args.minor:
        new_version = bump_semver(current_version, part="minor")
    else:
        new_version = bump_semver(current_version, part="patch")

    new_code = int(args.code) if args.code > 0 else current_code + 1
    if new_code <= current_code and not args.code:
        new_code = current_code + 1

    write_gradle(new_version, new_code)
    print(f"Bumped Android shell {current_version}/{current_code} -> {new_version}/{new_code}")
    print(f"  {GRADLE.relative_to(ROOT)}")
    print()
    print("Next:")
    print("  ./mobile_kivy/build_apk_fast.sh")
    print("  .venv/bin/python scripts/publish_android_shell_apk.py")
    print("  git add static/mobile/hbe.apk static/mobile/hbe_shell_version.json android/app/build.gradle.kts")
    print("  then Mac→GitHub push and AWS Server sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
