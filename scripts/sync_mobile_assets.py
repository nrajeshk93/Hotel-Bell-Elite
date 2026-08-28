#!/usr/bin/env python3
"""Copy mobile UI into Android assets (API root is resolved inside the HTML)."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "mobile_kivy" / "preview" / "mobile_ui_preview.html"
ASSET_SRC = ROOT / "mobile_kivy" / "assets"
OUT = ROOT / "android" / "app" / "src" / "main" / "assets" / "mobile"


def main() -> int:
    if not PREVIEW.is_file():
        print(f"Missing {PREVIEW}", file=sys.stderr)
        return 1
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    shutil.copy2(PREVIEW, OUT / "mobile_ui_preview.html")
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for src in ASSET_SRC.glob(pattern):
            shutil.copy2(src, OUT / src.name)
    print(f"Synced mobile UI → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
