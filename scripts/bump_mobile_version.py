#!/usr/bin/env python3
"""Bump mobile_kivy version in buildozer.spec + version.py together.

Usage (from repo root):
  .venv/bin/python scripts/bump_mobile_version.py
  .venv/bin/python scripts/bump_mobile_version.py --set 0.2.0 --code 2
  .venv/bin/python scripts/bump_mobile_version.py --patch   # 0.1.0 -> 0.1.1, code += 1
  .venv/bin/python scripts/bump_mobile_version.py --minor   # 0.1.0 -> 0.2.0, code += 1
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "mobile_kivy" / "buildozer.spec"
VERSION_PY = ROOT / "mobile_kivy" / "hbe_mobile" / "version.py"


def read_current() -> tuple[str, int]:
    text = SPEC_PATH.read_text(encoding="utf-8")
    version_match = re.search(r"(?m)^version\s*=\s*(\S+)", text)
    code_match = re.search(r"(?m)^android\.numeric_version\s*=\s*(\d+)", text)
    if not version_match:
        raise SystemExit(f"Could not read version from {SPEC_PATH}")
    version = version_match.group(1).strip()
    code = int(code_match.group(1)) if code_match else 1
    return version, code


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


def write_spec(version: str, code: int) -> None:
    text = SPEC_PATH.read_text(encoding="utf-8")
    text, n1 = re.subn(r"(?m)^(version\s*=\s*)\S+", rf"\g<1>{version}", text, count=1)
    text, n2 = re.subn(
        r"(?m)^(android\.numeric_version\s*=\s*)\d+",
        rf"\g<1>{code}",
        text,
        count=1,
    )
    if n1 != 1:
        raise SystemExit("Failed to rewrite version= in buildozer.spec")
    if n2 != 1:
        # Insert after version line if missing.
        text = re.sub(
            r"(?m)^(version\s*=\s*\S+\s*)$",
            rf"\1\nandroid.numeric_version = {code}",
            text,
            count=1,
        )
    SPEC_PATH.write_text(text, encoding="utf-8")


def write_version_py(version: str, code: int) -> None:
    text = VERSION_PY.read_text(encoding="utf-8")
    text, n1 = re.subn(
        r'(?m)^(APP_VERSION\s*=\s*")[^"]*(")',
        rf"\g<1>{version}\2",
        text,
        count=1,
    )
    text, n2 = re.subn(
        r"(?m)^(APP_VERSION_CODE\s*=\s*)\d+",
        rf"\g<1>{code}",
        text,
        count=1,
    )
    if n1 != 1 or n2 != 1:
        raise SystemExit(f"Failed to rewrite constants in {VERSION_PY}")
    VERSION_PY.write_text(text, encoding="utf-8")


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

    write_spec(new_version, new_code)
    write_version_py(new_version, new_code)
    print(f"Bumped {current_version}/{current_code} -> {new_version}/{new_code}")
    print(f"  {SPEC_PATH.relative_to(ROOT)}")
    print(f"  {VERSION_PY.relative_to(ROOT)}")
    print()
    print("Next:")
    print("  cd mobile_kivy && buildozer android release")
    print("  .venv/bin/python scripts/publish_mobile_apk.py")
    print("  git add … && git push && AWS Server sync")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
