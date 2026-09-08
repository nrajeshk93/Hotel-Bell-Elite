#!/usr/bin/env python3
"""Send Hotel Bell Elite daily sales WhatsApp report for one date."""
from __future__ import annotations

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

os.chdir(ROOT)

try:
    from dotenv import load_dotenv

    load_dotenv(os.path.join(ROOT, ".env"))
except ImportError:
    pass

from hotel_sales_whatsapp_report import (  # noqa: E402
    send_daily_sales_whatsapp_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="Sales date YYYY-MM-DD")
    parser.add_argument(
        "--phone",
        action="append",
        default=[],
        help="Recipient e.g. +918940651222 (repeatable). Default: env list.",
    )
    parser.add_argument("--force", action="store_true", help="Resend even if already logged")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print body params + image path; do not call Meta",
    )
    args = parser.parse_args()

    phones = args.phone or None
    result = send_daily_sales_whatsapp_report(
        args.date,
        phones=phones,
        dry_run=args.dry_run,
        force=args.force,
        skip_if_sent=not args.force,
    )

    print("Template body variables (positional):")
    for i, value in enumerate(result.get("body_params") or [], start=1):
        print(f"  {{{{{i}}}}}: {value}")
    if result.get("image_path"):
        print(f"Image: {result['image_path']}")
    if result.get("source_notes"):
        print(f"Sources: {result['source_notes']}")
    if result.get("totals"):
        print(f"Totals: {json.dumps(result['totals'], default=str)}")
    if result.get("per_phone"):
        print("Per phone:")
        for row in result["per_phone"]:
            status = "ok" if row.get("ok") else f"error: {row.get('error')}"
            print(f"  {row.get('phone')}: {status}")
            if row.get("wa_message_id"):
                print(f"    wa_message_id={row['wa_message_id']}")
    elif result.get("reason") or result.get("error"):
        print(result.get("reason") or result.get("error"))

    if args.dry_run or result.get("dry_run"):
        print(json.dumps({k: result.get(k) for k in (
            "ok", "dry_run", "sales_date", "template_name", "recipients",
            "source_notes", "skipped",
        ) if k in result}, indent=2, default=str))
        sys.exit(0)

    if result.get("skipped"):
        print(json.dumps(result, indent=2, default=str))
        sys.exit(0)

    sys.exit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
