#!/usr/bin/env python3
"""Copy mobile UI into Android assets and patch API base URL for production."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PREVIEW = ROOT / "mobile_kivy" / "preview" / "mobile_ui_preview.html"
ASSET_SRC = ROOT / "mobile_kivy" / "assets"
OUT = ROOT / "android" / "app" / "src" / "main" / "assets" / "mobile"
API_ROOT = "https://belleliteaccounts.com"


def main() -> int:
    if not PREVIEW.is_file():
        print(f"Missing {PREVIEW}", file=sys.stderr)
        return 1
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    html = PREVIEW.read_text(encoding="utf-8")
    if "HBE_API_ROOT" not in html:
        html = html.replace(
            "function previewFetch(url, options) {",
            f'const HBE_API_ROOT = "{API_ROOT}";\n    function previewFetch(url, options) {{',
            1,
        )
        html = html.replace(
            "return fetch(url, opts);",
            "const full = url.startsWith('http') ? url : (HBE_API_ROOT + url);\n      return fetch(full, opts);",
            1,
        )
    (OUT / "mobile_ui_preview.html").write_text(html, encoding="utf-8")
    for pattern in ("*.png", "*.jpg", "*.jpeg", "*.webp"):
        for src in ASSET_SRC.glob(pattern):
            shutil.copy2(src, OUT / src.name)
    print(f"Synced mobile UI → {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
