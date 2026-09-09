"""Daily Hotel Bell Elite sales WhatsApp report via Meta template.

Live template (APPROVED, language ``en``): ``hotel_sales_update`` — **7** body params.
Pending Room Transfer template (not live until env says so) — **8** body params:

  HEADER: IMAGE (generated daily JPEG)
  BODY positional (index order for Meta send):
    {{1}} date label  e.g. ``08 Sep 26``
    {{2}} Actual Sales
    {{3}} Cash
    {{4}} UPI
    {{5}} Card
    {{6}} Credit  (excludes Room Transfer when 8-param mode)
    {{7}} Difference
    {{8}} Room Transfer  (8-param mode only)

Amounts are plain Indian-grouped integers without the ₹ glyph (template has ₹).

Env:
  WHATSAPP_SALES_REPORT_TEMPLATE=hotel_sales_update
  WHATSAPP_SALES_REPORT_TEMPLATE_LANGUAGE=en
  WHATSAPP_SALES_REPORT_RECIPIENTS=+918940651222,+919150000267,+919531825665,+919933268361
  WHATSAPP_SALES_REPORT_SCHEDULE=1
  WHATSAPP_SALES_REPORT_SCHEDULE_TIME=23:59
  WHATSAPP_SALES_REPORT_SCHEDULE_TZ=Asia/Kolkata
  # Keep 0 until the new Meta template is approved, then set template name + INCLUDE=1
  WHATSAPP_SALES_REPORT_INCLUDE_ROOM_TRANSFER=0
  # Also auto-enables 8-param mode when template name ends with ``_rt``
  # (e.g. hotel_sales_update_rt) or equals a pending RT template name.

Reuses ``whatsapp_client`` (``upload_media_file`` / ``send_template_message``) — same
path as ``hotel_feedback_whatsapp`` / ``pos_invoice_whatsapp``.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import whatsapp_client as wa
from db import (
    get_db,
    hotel_sales_entry_from_invoices,
    list_pos_invoices,
    pos_sales_entry_from_invoices,
)
from sales_whatsapp_report_image import (
    _inr_parts,
    collect_daily_sales,
    generate_daily_sales_report_image,
    report_image_mime_type,
)

log = logging.getLogger(__name__)

DEFAULT_TEMPLATE_NAME = "hotel_sales_update"
DEFAULT_TEMPLATE_LANGUAGE = "en"
DEFAULT_COMPANY = "HBE"
DEFAULT_RECIPIENTS = (
    "+918940651222,+919150000267,+919531825665,+919933268361"
)
DEFAULT_SCHEDULE_TIME = "23:59"
DEFAULT_SCHEDULE_TZ = "Asia/Kolkata"
OUTLETS = ("Hotel", "Restaurant", "Bar")

# Matches app.SALES_ENTRY_TOTAL_KEYS used by get_difference (Hotel).
_TENDER_KEYS_FOR_DIFFERENCE = (
    "cash",
    "card",
    "upi",
    "room_credit",
    "bor",
    "online_order",
)
# Body {{6}} Credit — Guest Credit + Employee Credit + BOR.
_CREDIT_KEYS = ("room_credit", "staff_account", "bor")



def sales_report_include_room_transfer() -> bool:
    """True when the Meta body should include {{8}} Room Transfer (8 params).

    Default **False** so live ``hotel_sales_update`` keeps sending **7** body params.

    Enable by either:
      - ``WHATSAPP_SALES_REPORT_INCLUDE_ROOM_TRANSFER`` = 1/true/yes/on, or
      - template name (``WHATSAPP_SALES_REPORT_TEMPLATE``) ends with ``_rt``
        (e.g. ``hotel_sales_update_rt``) or equals a known pending RT name.
    After Meta approval: set the new template name and INCLUDE_ROOM_TRANSFER=1.
    """
    raw = (
        os.environ.get("WHATSAPP_SALES_REPORT_INCLUDE_ROOM_TRANSFER") or ""
    ).strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    name, _ = sales_report_template_config()
    name_l = (name or "").strip().lower()
    if name_l.endswith("_rt"):
        return True
    # Pending / draft Meta names (document markers; do not switch live env yet).
    if name_l in {"hotel_sales_update_rt", "hotel_sales_update_with_rt"}:
        return True
    return False


def sum_pos_room_transfer_for_sales_date(conn, sales_date: str) -> float:
    """Sum ``room_transfer`` payments for restaurant+bar invoices on ``sales_date``.

    Uses the same invoice set as Sales Entry / the WhatsApp report day
    (``list_pos_invoices`` with ``generated_only=True``, ``order_date`` window),
    reading ``payment_amounts['room_transfer']`` (from ``pos_invoice_payments``).
    """
    day = str(sales_date)[:10]
    total = 0.0
    for outlet_key in ("restaurant", "bar"):
        invoices = list_pos_invoices(
            conn,
            date_from=day,
            date_to=day,
            outlet=outlet_key,
            generated_only=True,
        )
        for inv in invoices or []:
            if str((inv or {}).get("status") or "open").strip().lower() == "cancelled":
                continue
            amounts = (inv or {}).get("payment_amounts")
            if not isinstance(amounts, dict):
                amounts = {}
            total += _money(amounts.get("room_transfer"))
    return _round2(total)


def sales_report_template_config() -> tuple[str, str]:
    name = (
        os.environ.get("WHATSAPP_SALES_REPORT_TEMPLATE") or DEFAULT_TEMPLATE_NAME
    ).strip()
    lang = (
        os.environ.get("WHATSAPP_SALES_REPORT_TEMPLATE_LANGUAGE")
        or DEFAULT_TEMPLATE_LANGUAGE
    ).strip()
    return name or DEFAULT_TEMPLATE_NAME, lang or DEFAULT_TEMPLATE_LANGUAGE


def sales_report_recipients(raw: str | None = None) -> list[str]:
    text = raw if raw is not None else (
        os.environ.get("WHATSAPP_SALES_REPORT_RECIPIENTS") or DEFAULT_RECIPIENTS
    )
    return wa.parse_whatsapp_recipients(text)


def sales_report_schedule_enabled() -> bool:
    return (os.environ.get("WHATSAPP_SALES_REPORT_SCHEDULE") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def sales_report_schedule_tz() -> str:
    return (
        os.environ.get("WHATSAPP_SALES_REPORT_SCHEDULE_TZ") or DEFAULT_SCHEDULE_TZ
    ).strip() or DEFAULT_SCHEDULE_TZ


def sales_report_schedule_time() -> tuple[int, int]:
    raw = (
        os.environ.get("WHATSAPP_SALES_REPORT_SCHEDULE_TIME") or DEFAULT_SCHEDULE_TIME
    ).strip() or DEFAULT_SCHEDULE_TIME
    try:
        hh, mm = raw.split(":", 1)
        return max(0, min(23, int(hh))), max(0, min(59, int(mm)))
    except (TypeError, ValueError):
        return 23, 59


def schedule_now() -> datetime:
    return datetime.now(ZoneInfo(sales_report_schedule_tz()))


def schedule_today_iso() -> str:
    return schedule_now().date().isoformat()


def _money(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _round2(value: float) -> float:
    return round(float(value) + 1e-9, 2) if value >= 0 else round(float(value) - 1e-9, 2)


def whatsapp_template_amount_text(value: Any) -> str:
    """Indian-grouped integer string without ₹ (mirrors Textile helper)."""
    neg, grouped = _inr_parts(value)
    return f"{'-' if neg else ''}{grouped}"


def sales_report_date_label(sales_date_iso: str) -> str:
    """Body {{1}} — Meta example style ``08 Sep 26``."""
    try:
        dt = datetime.strptime(str(sales_date_iso)[:10], "%Y-%m-%d")
        return dt.strftime("%d %b %y")
    except ValueError:
        return str(sales_date_iso or "")


def ensure_sales_whatsapp_reports_schema(conn) -> None:
    """Idempotent SQLite table for nightly send log / skip-if-sent."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sales_update_whatsapp_reports (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL DEFAULT 'All',
            sales_date      TEXT    NOT NULL,
            template_name   TEXT    NOT NULL DEFAULT '',
            recipients      TEXT    NOT NULL DEFAULT '',
            status          TEXT    NOT NULL DEFAULT 'pending',
            error_message   TEXT    NOT NULL DEFAULT '',
            sent_count      INTEGER NOT NULL DEFAULT 0,
            failed_count    INTEGER NOT NULL DEFAULT 0,
            image_path      TEXT    NOT NULL DEFAULT '',
            body_params     TEXT    NOT NULL DEFAULT '[]',
            source_notes    TEXT    NOT NULL DEFAULT '',
            sent_at         TEXT,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(company, location, sales_date)
        )
        """
    )
    conn.commit()


def _load_sales_update_values(conn, location: str, sales_date: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT sales_entry_values FROM sales_updates
        WHERE company = ? AND location = ? AND sales_date = ?
        """,
        (DEFAULT_COMPANY, location, sales_date),
    ).fetchone()
    if not row:
        return {}
    raw = row["sales_entry_values"] if isinstance(row, sqlite3.Row) else row[0]
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _invoice_entry_for_outlet(conn, location: str, sales_date: str) -> dict[str, Any]:
    if location == "Hotel":
        return dict(hotel_sales_entry_from_invoices(conn, sales_date) or {})
    outlet_key = "restaurant" if location == "Restaurant" else "bar"
    return dict(pos_sales_entry_from_invoices(conn, outlet_key, sales_date) or {})


def _merge_outlet_entry(
    su: dict[str, Any], inv: dict[str, Any]
) -> tuple[dict[str, float], str]:
    """Prefer sales_updates when total_sales is usable; else invoice-derived.

    Manual cash-count fields (actual_cash / tips / expense / staff_account) always
    prefer the sales_updates row when present.
    """
    su_total = _money(su.get("total_sales"))
    inv_total = _money(inv.get("total_sales"))
    tender_keys = (
        "cash",
        "card",
        "upi",
        "room_credit",
        "bor",
        "online_order",
        "staff_account",
    )
    out: dict[str, float] = {}
    if su_total > 0.005:
        source = "sales_updates"
        out["total_sales"] = _round2(su_total)
        for key in tender_keys:
            out[key] = _round2(_money(su.get(key)))
    else:
        source = "invoices" if inv_total > 0.005 or any(_money(inv.get(k)) for k in tender_keys) else "empty"
        out["total_sales"] = _round2(inv_total)
        for key in tender_keys:
            # Prefer invoice tender; fall back to sales_updates if invoice missing key.
            if key in inv or key not in su:
                out[key] = _round2(_money(inv.get(key)))
            else:
                out[key] = _round2(_money(su.get(key)))
    # Manual overlays from Sales Update UI.
    for key in ("actual_cash", "tips", "expense"):
        if key in su:
            out[key] = _round2(_money(su.get(key)))
        else:
            out.setdefault(key, 0.0)
    if "staff_account" in su and su_total <= 0.005:
        # Keep employee credit from SU even when totals come from invoices.
        out["staff_account"] = _round2(_money(su.get("staff_account")))
    return out, source


def outlet_difference(vals: dict[str, Any], location: str) -> float:
    """Reuse Sales Update Difference rules from app.py (no Flask import).

    Hotel: total_sales − (cash+card+upi+room_credit+bor+online_order)  [= get_difference]
    Restaurant/Bar: cash − actual_cash  [= get_cash_actual_difference]
    """
    if location == "Hotel":
        tenders = sum(_money(vals.get(k)) for k in _TENDER_KEYS_FOR_DIFFERENCE)
        return _round2(_money(vals.get("total_sales")) - tenders)
    return _round2(_money(vals.get("cash")) - _money(vals.get("actual_cash")))


def collect_sales_report_metrics(conn, sales_date: str) -> dict[str, Any]:
    """Aggregate Hotel + Restaurant + Bar body metrics for one sales date.

    Always collects ``room_transfer`` (true POS RT payments). Body length is 7
    unless ``sales_report_include_room_transfer()`` — then Credit excludes RT and
    {{8}} is Room Transfer. Difference formula is unchanged.
    """
    day = str(sales_date)[:10]
    per_outlet: dict[str, Any] = {}
    source_notes: list[str] = []
    totals = {
        "actual_sales": 0.0,
        "cash": 0.0,
        "upi": 0.0,
        "card": 0.0,
        "credit": 0.0,
        "difference": 0.0,
        "room_transfer": 0.0,
    }
    for location in OUTLETS:
        su = _load_sales_update_values(conn, location, day)
        inv = _invoice_entry_for_outlet(conn, location, day)
        merged, source = _merge_outlet_entry(su, inv)
        diff = outlet_difference(merged, location)
        credit = sum(_money(merged.get(k)) for k in _CREDIT_KEYS)
        per_outlet[location] = {
            "values": merged,
            "source": source,
            "difference": diff,
            "credit": _round2(credit),
        }
        source_notes.append(f"{location}:{source}")
        totals["actual_sales"] += _money(merged.get("total_sales"))
        totals["cash"] += _money(merged.get("cash"))
        totals["upi"] += _money(merged.get("upi"))
        totals["card"] += _money(merged.get("card"))
        totals["credit"] += credit
        totals["difference"] += diff

    room_transfer = sum_pos_room_transfer_for_sales_date(conn, day)
    totals["room_transfer"] = room_transfer

    for key in totals:
        totals[key] = _round2(totals[key])

    include_rt = sales_report_include_room_transfer()
    credit_for_body = totals["credit"]
    if include_rt:
        # Peel RT out of Credit for {{6}}; RT is reported as {{8}}.
        credit_for_body = _round2(totals["credit"] - room_transfer)
        totals["credit"] = credit_for_body

    body_params = [
        sales_report_date_label(day),
        whatsapp_template_amount_text(totals["actual_sales"]),
        whatsapp_template_amount_text(totals["cash"]),
        whatsapp_template_amount_text(totals["upi"]),
        whatsapp_template_amount_text(totals["card"]),
        whatsapp_template_amount_text(credit_for_body),
        whatsapp_template_amount_text(totals["difference"]),
    ]
    if include_rt:
        body_params.append(whatsapp_template_amount_text(room_transfer))
    return {
        "sales_date": day,
        "date_label": body_params[0],
        "totals": totals,
        "body_params": body_params,
        "include_room_transfer": include_rt,
        "per_outlet": per_outlet,
        "source_notes": "; ".join(source_notes),
    }


def generate_sales_report_image(conn, sales_date: str) -> str:
    """Build image from the same merged outlet totals as the template body."""
    from datetime import timedelta

    day = str(sales_date)[:10]
    metrics = collect_sales_report_metrics(conn, day)
    per = metrics["per_outlet"]

    def _outlet_total(loc_map: dict, location: str) -> float:
        return float((loc_map.get(location) or {}).get("values", {}).get("total_sales") or 0)

    outlet_totals = {
        "hotel": _outlet_total(per, "Hotel"),
        "restaurant": _outlet_total(per, "Restaurant"),
        "bar": _outlet_total(per, "Bar"),
    }

    prior_outlet_totals = None
    prior_difference = None
    try:
        prior = (datetime.strptime(day, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    except ValueError:
        prior = None
    if prior:
        prior_metrics = collect_sales_report_metrics(conn, prior)
        prior_per = prior_metrics["per_outlet"]
        prior_outlet_totals = {
            "hotel": _outlet_total(prior_per, "Hotel"),
            "restaurant": _outlet_total(prior_per, "Restaurant"),
            "bar": _outlet_total(prior_per, "Bar"),
        }
        prior_difference = float(prior_metrics["totals"].get("difference") or 0)

    payload = collect_daily_sales(
        conn,
        day,
        outlet_totals=outlet_totals,
        prior_outlet_totals=prior_outlet_totals,
    )
    payload["difference"] = float(metrics["totals"].get("difference") or 0)
    if prior_difference is not None:
        payload["prior_difference"] = prior_difference
        payload["trend_difference"] = None  # let image module compute via prior_difference
    return generate_daily_sales_report_image(payload)


def _load_report_log(conn, sales_date: str) -> dict[str, Any] | None:
    ensure_sales_whatsapp_reports_schema(conn)
    row = conn.execute(
        """
        SELECT status, sent_count, failed_count, recipients, error_message, sent_at
        FROM sales_update_whatsapp_reports
        WHERE company = ? AND location = 'All' AND sales_date = ?
        """,
        (DEFAULT_COMPANY, str(sales_date)[:10]),
    ).fetchone()
    return dict(row) if row else None


def _already_sent(conn, sales_date: str) -> dict[str, Any] | None:
    """Return the log row only when the day was fully delivered.

    status ``partial`` / ``failed`` / ``pending`` must NOT block retries.
    Full success = status ``sent``, sent_count > 0, and failed_count == 0.
    """
    item = _load_report_log(conn, sales_date)
    if not item:
        return None
    status = str(item.get("status") or "").lower()
    sent_count = int(item.get("sent_count") or 0)
    failed_count = int(item.get("failed_count") or 0)
    if status == "sent" and sent_count > 0 and failed_count == 0:
        return item
    return None


def _failed_phones_from_log(item: dict[str, Any]) -> list[str]:
    """Best-effort list of phones that still need a send after a partial run.

    error_message lines look like ``+91…: send failed``. Recipients that appear
    only in ``recipients`` (and not as a failed phone) are treated as already sent.
    """
    recipients = [
        wa.normalise_whatsapp_number(p)
        for p in str(item.get("recipients") or "").split(",")
        if p.strip()
    ]
    recipients = [p for p in recipients if p]
    failed: list[str] = []
    for part in str(item.get("error_message") or "").split(";"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        phone = wa.normalise_whatsapp_number(part.split(":", 1)[0].strip())
        if phone:
            failed.append(phone)
    # De-dupe preserving order
    seen: set[str] = set()
    out: list[str] = []
    for p in failed:
        if p not in seen:
            seen.add(p)
            out.append(p)
    if out:
        return out
    # Fallback: if we cannot parse failures, retry everyone (safer than skipping).
    return recipients


def _upsert_report_log(
    conn,
    *,
    sales_date: str,
    template_name: str,
    recipients: list[str],
    status: str,
    sent_count: int,
    failed_count: int,
    error_message: str = "",
    image_path: str = "",
    body_params: list[str] | None = None,
    source_notes: str = "",
) -> None:
    ensure_sales_whatsapp_reports_schema(conn)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        INSERT INTO sales_update_whatsapp_reports (
            company, location, sales_date, template_name, recipients, status,
            error_message, sent_count, failed_count, image_path, body_params,
            source_notes, sent_at, created_at, updated_at
        ) VALUES (?, 'All', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company, location, sales_date) DO UPDATE SET
            template_name = excluded.template_name,
            recipients = excluded.recipients,
            status = excluded.status,
            error_message = excluded.error_message,
            sent_count = excluded.sent_count,
            failed_count = excluded.failed_count,
            image_path = excluded.image_path,
            body_params = excluded.body_params,
            source_notes = excluded.source_notes,
            sent_at = excluded.sent_at,
            updated_at = excluded.updated_at
        """,
        (
            DEFAULT_COMPANY,
            str(sales_date)[:10],
            template_name,
            ",".join(recipients),
            status,
            (error_message or "")[:2000],
            int(sent_count),
            int(failed_count),
            image_path or "",
            json.dumps(body_params or []),
            source_notes or "",
            now if status in ("sent", "partial") else None,
            now,
            now,
        ),
    )
    conn.commit()


def send_daily_sales_whatsapp_report(
    sales_date: str,
    *,
    phones: list[str] | None = None,
    dry_run: bool = False,
    force: bool = False,
    skip_if_sent: bool = True,
) -> dict[str, Any]:
    """Generate image, upload header media, send ``hotel_sales_update`` to recipients."""
    day = str(sales_date)[:10]
    template_name, template_lang = sales_report_template_config()
    recipients = phones if phones is not None else sales_report_recipients()
    recipients = [wa.normalise_whatsapp_number(p) for p in recipients]
    recipients = [p for p in recipients if p]
    # De-dupe preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for p in recipients:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    recipients = unique

    conn = get_db()
    try:
        conn.row_factory = sqlite3.Row
    except Exception:
        pass

    try:
        ensure_sales_whatsapp_reports_schema(conn)
        prior_log = _load_report_log(conn, day) if not dry_run else None
        prior_sent_count = 0
        if skip_if_sent and not force and not dry_run:
            fully_done = _already_sent(conn, day)
            if fully_done:
                return {
                    "ok": True,
                    "skipped": True,
                    "reason": f"Already sent for {day} (sent_count={fully_done.get('sent_count')}).",
                    "sales_date": day,
                    "prior": fully_done,
                }
            # Partial prior: retry only the phones that failed last time
            # (when using the default recipient list; explicit phones= keeps caller's list).
            if (
                phones is None
                and prior_log
                and str(prior_log.get("status") or "").lower() == "partial"
            ):
                retry_phones = _failed_phones_from_log(prior_log)
                if retry_phones:
                    recipients = retry_phones
                    prior_sent_count = int(prior_log.get("sent_count") or 0)
                    log.info(
                        "Retrying %d failed recipient(s) after partial send for %s",
                        len(recipients),
                        day,
                    )

        metrics = collect_sales_report_metrics(conn, day)
        body_params = list(metrics["body_params"])
        image_path = generate_sales_report_image(conn, day)

        result: dict[str, Any] = {
            "ok": True,
            "sales_date": day,
            "template_name": template_name,
            "template_language": template_lang,
            "body_params": body_params,
            "totals": metrics["totals"],
            "source_notes": metrics["source_notes"],
            "per_outlet": {
                loc: {
                    "source": info["source"],
                    "difference": info["difference"],
                    "total_sales": info["values"].get("total_sales"),
                    "cash": info["values"].get("cash"),
                    "upi": info["values"].get("upi"),
                    "card": info["values"].get("card"),
                    "credit": info["credit"],
                    "actual_cash": info["values"].get("actual_cash"),
                }
                for loc, info in metrics["per_outlet"].items()
            },
            "image_path": image_path,
            "recipients": recipients,
            "dry_run": bool(dry_run) or not wa.whatsapp_live_sends_allowed(),
        }

        if dry_run or not wa.whatsapp_live_sends_allowed():
            result["reason"] = (
                "Dry-run only (WHATSAPP_DRY_RUN or --dry-run); no Meta HTTP."
                if dry_run or not wa.whatsapp_live_sends_allowed()
                else "Dry-run."
            )
            result["send_path"] = "dry_run"
            return result

        if not recipients:
            result["ok"] = False
            result["error"] = "No WhatsApp recipients configured."
            return result

        if not wa.whatsapp_configured():
            result["ok"] = False
            result["error"] = (
                "WhatsApp API is not configured. "
                "Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID."
            )
            return result

        mime = report_image_mime_type()
        ok_up, err_up, body_up = wa.upload_media_file(image_path, mime)
        media_id = ""
        if isinstance(body_up, dict):
            media_id = str(body_up.get("id") or "").strip()
        if not (ok_up and media_id):
            result["ok"] = False
            result["error"] = err_up or "Could not upload sales report image to WhatsApp."
            _upsert_report_log(
                conn,
                sales_date=day,
                template_name=template_name,
                recipients=recipients,
                status="failed",
                sent_count=0,
                failed_count=len(recipients),
                error_message=result["error"],
                image_path=image_path,
                body_params=body_params,
                source_notes=metrics["source_notes"],
            )
            return result

        result["media_id"] = media_id
        per_phone: list[dict[str, Any]] = []
        sent_count = 0
        failed_count = 0
        errors: list[str] = []
        for phone in recipients:
            ok, err, body = wa.send_template_message(
                phone,
                template_name,
                template_lang,
                body_parameters=body_params,
                header_image_id=media_id,
            )
            wa_id = wa.first_message_id(body) if isinstance(body, dict) else ""
            entry = {
                "phone": phone,
                "ok": bool(ok),
                "error": (err or "")[:500],
                "wa_message_id": wa_id,
            }
            per_phone.append(entry)
            if ok:
                sent_count += 1
            else:
                failed_count += 1
                errors.append(f"{phone}: {(err or 'send failed')[:200]}")

        # Accumulate with any prior partial successes so a retry can reach "sent".
        total_sent = prior_sent_count + sent_count
        total_failed = failed_count
        # Recipients column: prefer full intended list from prior log when retrying.
        log_recipients = recipients
        if prior_log and prior_sent_count > 0:
            prior_recipients = [
                wa.normalise_whatsapp_number(p)
                for p in str(prior_log.get("recipients") or "").split(",")
                if p.strip()
            ]
            prior_recipients = [p for p in prior_recipients if p]
            if prior_recipients:
                log_recipients = prior_recipients

        result["per_phone"] = per_phone
        result["sent_count"] = total_sent
        result["failed_count"] = total_failed
        result["errors"] = errors
        result["ok"] = total_sent > 0 and total_failed == 0
        result["send_path"] = "template_image_header"
        if total_sent > 0 and total_failed == 0:
            status = "sent"
        elif total_sent > 0:
            status = "partial"
        else:
            status = "failed"
        _upsert_report_log(
            conn,
            sales_date=day,
            template_name=template_name,
            recipients=log_recipients,
            status=status,
            sent_count=total_sent,
            failed_count=total_failed,
            error_message="; ".join(errors),
            image_path=image_path,
            body_params=body_params,
            source_notes=metrics["source_notes"],
        )
        if not result["ok"]:
            result["error"] = "; ".join(errors) or "WhatsApp send failed."
        return result
    finally:
        try:
            conn.close()
        except Exception:
            pass


def run_scheduled_sales_whatsapp_reports(
    sales_date_iso: str | None = None,
    *,
    dry_run: bool = False,
    force: bool = False,
) -> dict[str, Any]:
    """Cron entrypoint: send today's (or given) report unless already sent."""
    if not force and not sales_report_schedule_enabled():
        return {
            "ok": False,
            "skipped": True,
            "reason": "Schedule disabled (set WHATSAPP_SALES_REPORT_SCHEDULE=1).",
        }
    day = sales_date_iso or schedule_today_iso()
    return send_daily_sales_whatsapp_report(
        day,
        dry_run=dry_run,
        force=force,
        skip_if_sent=not force,
    )
