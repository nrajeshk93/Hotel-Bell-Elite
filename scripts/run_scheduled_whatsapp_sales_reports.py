#!/usr/bin/env python3
"""
Auto-send the WhatsApp daily sales report (Hotel + Restaurant + Bar).

Default: today (Asia/Kolkata), 11:59 PM job via cron.
Skips if report already sent or outside the schedule window.
"""
from __future__ import annotations

import argparse
import fcntl
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
    run_scheduled_sales_whatsapp_reports,
    sales_report_schedule_time,
    schedule_now,
)

LOCK_PATH = os.path.join(ROOT, "logs", "whatsapp_sales_schedule.lock")


def _acquire_lock():
    os.makedirs(os.path.dirname(LOCK_PATH), exist_ok=True)
    fh = open(LOCK_PATH, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        return None
    return fh


def _schedule_window_delta(now, sched_h: int, sched_m: int) -> tuple[int, bool]:
    """Return (delta_minutes, wrapped_past_midnight).

    Cron target e.g. 23:59 with a job at 00:05 → raw delta is negative, so we
    add 24h (wrapped=True). Same-evening 23:59–00:14 stays wrapped=False until
    the clock crosses midnight.
    """
    now_minutes = now.hour * 60 + now.minute
    target_minutes = sched_h * 60 + sched_m
    raw_delta = now_minutes - target_minutes
    if raw_delta < 0:
        return raw_delta + 24 * 60, True
    return raw_delta, False


def resolve_schedule_sales_date(now, sched_h: int, sched_m: int, explicit_date: str | None) -> str:
    """Sales date for the nightly job.

    Self-check (Asia/Kolkata, target 23:59, window 15 min):
      - now=23:59 → today (same-evening, not wrapped)
      - now=00:05 → yesterday (post-midnight wrap inside window)
      - now=00:20 → today calendar (outside window; caller may skip)
    Explicit --date always wins.
    """
    from datetime import timedelta

    if explicit_date:
        return str(explicit_date)[:10]
    delta, wrapped = _schedule_window_delta(now, sched_h, sched_m)
    # Post-midnight portion of the allowed window → sales belong to yesterday.
    if wrapped and 0 <= delta <= 15:
        return (now.date() - timedelta(days=1)).isoformat()
    return now.date().isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", help="Sales date YYYY-MM-DD (default: today in schedule TZ)")
    parser.add_argument("--dry-run", action="store_true", help="Check readiness only; do not send")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send even if already sent; ignore schedule disabled flag",
    )
    parser.add_argument(
        "--ignore-time-window",
        action="store_true",
        help="Run even outside the scheduled minute (for manual testing)",
    )
    args = parser.parse_args()

    now = schedule_now()
    sched_h, sched_m = sales_report_schedule_time()
    delta, _wrapped = _schedule_window_delta(now, sched_h, sched_m)

    if not args.ignore_time_window and not args.force and not args.date and not args.dry_run:
        # Allow cron drift after the target: 23:59–00:14 window (15 minutes),
        # including wrap past midnight for a 23:59 cron that fires at 00:0x.
        if not 0 <= delta <= 15:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "skipped": True,
                        "reason": (
                            f'Outside schedule window (now {now.strftime("%H:%M")} '
                            f"{now.tzinfo}; expected ~{sched_h:02d}:{sched_m:02d}). "
                            "Use --ignore-time-window to run anyway."
                        ),
                    },
                    indent=2,
                )
            )
            sys.exit(0)

    sales_date = resolve_schedule_sales_date(now, sched_h, sched_m, args.date)
    lock_fh = _acquire_lock()
    if lock_fh is None:
        print(
            json.dumps(
                {
                    "ok": False,
                    "skipped": True,
                    "date": sales_date,
                    "reason": "Another WhatsApp schedule job is already running.",
                },
                indent=2,
            )
        )
        sys.exit(0)

    try:
        result = run_scheduled_sales_whatsapp_reports(
            sales_date_iso=sales_date,
            dry_run=args.dry_run,
            force=args.force,
        )
        # Avoid dumping huge per_outlet detail in cron logs.
        slim = {
            k: result.get(k)
            for k in (
                "ok",
                "skipped",
                "reason",
                "error",
                "sales_date",
                "template_name",
                "body_params",
                "source_notes",
                "image_path",
                "recipients",
                "sent_count",
                "failed_count",
                "per_phone",
                "dry_run",
                "errors",
            )
            if k in result
        }
        print(json.dumps(slim, indent=2, default=str))
        if result.get("skipped") and not args.force:
            sys.exit(0)
        sys.exit(0 if result.get("ok") else 1)
    finally:
        try:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        except Exception:
            pass
        lock_fh.close()


if __name__ == "__main__":
    main()
