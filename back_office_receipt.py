"""Back Office Receipt — Accounts ledger for incoming hotel advances/payments."""

from __future__ import annotations

from datetime import date

from flask import jsonify, render_template, request, send_file, url_for

from db import (
    allocate_back_office_receipt_no,
    ensure_back_office_receipt_schema,
    ensure_hotel_invoice_credits_schema,
    get_agency,
    get_db,
    indian_fiscal_year_bounds,
    list_agencies,
)

PAYMENT_MODES = (
    ("cash", "Cash"),
    ("cheque", "Cheque"),
    ("draft", "Draft"),
    ("bank_transfer", "Bank Transfer"),
)
PAYMENT_MODE_LABELS = {k: v for k, v in PAYMENT_MODES}

_ONES = (
    "",
    "One",
    "Two",
    "Three",
    "Four",
    "Five",
    "Six",
    "Seven",
    "Eight",
    "Nine",
    "Ten",
    "Eleven",
    "Twelve",
    "Thirteen",
    "Fourteen",
    "Fifteen",
    "Sixteen",
    "Seventeen",
    "Eighteen",
    "Nineteen",
)
_TENS = (
    "",
    "",
    "Twenty",
    "Thirty",
    "Forty",
    "Fifty",
    "Sixty",
    "Seventy",
    "Eighty",
    "Ninety",
)

_pop_auth_notice = None
_get_user = None


def _bind_helpers(*, pop_auth_notice, get_user):
    global _pop_auth_notice, _get_user
    _pop_auth_notice = pop_auth_notice
    _get_user = get_user


def _parse_money(value) -> float:
    raw = str(value or "").strip().replace(",", "")
    if not raw:
        return 0.0
    try:
        return round(float(raw), 2)
    except (TypeError, ValueError):
        return 0.0


def _two_digit_words(n: int) -> str:
    if n < 20:
        return _ONES[n]
    tens, ones = divmod(n, 10)
    if ones:
        return f"{_TENS[tens]} {_ONES[ones]}"
    return _TENS[tens]


def _three_digit_words(n: int) -> str:
    if n < 100:
        return _two_digit_words(n)
    hundreds, rem = divmod(n, 100)
    head = f"{_ONES[hundreds]} Hundred"
    if rem:
        return f"{head} {_two_digit_words(rem)}"
    return head


def amount_in_indian_words(amount) -> str:
    """Return Indian-style rupee words, e.g. 'Rupees One Thousand Only'."""
    try:
        value = float(amount or 0)
    except (TypeError, ValueError):
        value = 0.0
    if value < 0:
        value = abs(value)
    rupees = int(value)
    paise = int(round((value - rupees) * 100))
    if paise == 100:
        rupees += 1
        paise = 0

    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"

    parts = []
    crore, rem = divmod(rupees, 10000000)
    if crore:
        parts.append(f"{_three_digit_words(crore)} Crore")
    lakh, rem = divmod(rem, 100000)
    if lakh:
        parts.append(f"{_three_digit_words(lakh)} Lakh")
    thousand, rem = divmod(rem, 1000)
    if thousand:
        parts.append(f"{_three_digit_words(thousand)} Thousand")
    if rem:
        parts.append(_three_digit_words(rem))

    text = " ".join(p for p in parts if p).strip() or "Zero"
    result = f"Rupees {text}"
    if paise:
        result += f" and {_two_digit_words(paise)} Paise"
    return f"{result} Only"


def _parse_iso_date(raw: str, *, fallback: date | None = None) -> date | None:
    text = str(raw or "").strip()
    if not text:
        return fallback
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _normalize_payment_mode(value) -> str:
    mode = str(value or "cash").strip().lower().replace(" ", "_").replace("-", "_")
    if mode in {"bank", "neft", "rtgs", "upi", "transfer"}:
        mode = "bank_transfer"
    if mode not in PAYMENT_MODE_LABELS:
        return ""
    return mode


def _receipt_dict(row) -> dict:
    mode = (row["payment_mode"] or "cash") if row else "cash"
    return {
        "id": int(row["id"]),
        "receipt_no": row["receipt_no"] or "",
        "fiscal_year": row["fiscal_year"] or "",
        "seq": int(row["seq"] or 0),
        "receipt_date": row["receipt_date"] or "",
        "payer_name": row["payer_name"] or "",
        "agency_id": row["agency_id"],
        "amount": float(row["amount"] or 0),
        "amount_words": row["amount_words"] or "",
        "payment_mode": mode,
        "payment_mode_label": PAYMENT_MODE_LABELS.get(mode, mode),
        "instrument_no": row["instrument_no"] or "",
        "instrument_date": row["instrument_date"] or "",
        "towards": row["towards"] or "",
        "created_at": row["created_at"] or "",
        "created_by": row["created_by"],
    }


def back_office_receipt_applied_total(conn, receipt_id: int) -> float:
    """Sum already applied from a BOR against hotel credit collections."""
    ensure_back_office_receipt_schema(conn)
    row = conn.execute(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM back_office_receipt_allocations
        WHERE receipt_id = ?
        """,
        (int(receipt_id),),
    ).fetchone()
    return float(row["total"] or 0) if row else 0.0


def list_pending_back_office_receipts_for_agency(
    conn, *, agency_id=None, agency_name: str = ""
) -> list[dict]:
    """BOR rows with remaining balance for an agency (by id, else payer name)."""
    ensure_back_office_receipt_schema(conn)
    agency_id_int = None
    try:
        if agency_id is not None and str(agency_id).strip() != "":
            agency_id_int = int(agency_id)
    except (TypeError, ValueError):
        agency_id_int = None
    name = str(agency_name or "").strip()
    if agency_id_int:
        rows = conn.execute(
            """
            SELECT *
            FROM back_office_receipts
            WHERE agency_id = ?
            ORDER BY receipt_date ASC, id ASC
            """,
            (agency_id_int,),
        ).fetchall()
    elif name:
        rows = conn.execute(
            """
            SELECT *
            FROM back_office_receipts
            WHERE lower(trim(payer_name)) = lower(?)
               OR (
                    agency_id IS NOT NULL
                    AND agency_id IN (
                        SELECT id FROM agencies WHERE lower(trim(name)) = lower(?)
                    )
               )
            ORDER BY receipt_date ASC, id ASC
            """,
            (name, name),
        ).fetchall()
    else:
        return []
    pending = []
    for row in rows:
        item = _receipt_dict(row)
        applied = back_office_receipt_applied_total(conn, item["id"])
        remaining = round(float(item["amount"] or 0) - applied, 2)
        if remaining <= 0.009:
            continue
        item["applied_amount"] = round(applied, 2)
        item["pending_amount"] = remaining
        pending.append(item)
    return pending


def insert_back_office_receipt_allocations(conn, payment_id: int, allocations: list[dict]):
    """Record BOR applications against a hotel credit payment."""
    ensure_back_office_receipt_schema(conn)
    for alloc in allocations or []:
        conn.execute(
            """
            INSERT INTO back_office_receipt_allocations
                (receipt_id, hotel_credit_payment_id, hotel_invoice_number, amount)
            VALUES (?, ?, '', ?)
            """,
            (
                int(alloc["receipt_id"]),
                int(payment_id),
                float(alloc["amount"]),
            ),
        )


def insert_back_office_receipt_invoice_allocations(
    conn, invoice_number: str, allocations: list[dict]
):
    """Record BOR applications against a hotel invoice settle payment."""
    ensure_back_office_receipt_schema(conn)
    inv_no = str(invoice_number or "").strip()
    if not inv_no:
        raise ValueError("Invoice number is required for Back Office Receipt allocation.")
    for alloc in allocations or []:
        conn.execute(
            """
            INSERT INTO back_office_receipt_allocations
                (receipt_id, hotel_credit_payment_id, hotel_invoice_number, amount)
            VALUES (?, NULL, ?, ?)
            """,
            (
                int(alloc["receipt_id"]),
                inv_no,
                float(alloc["amount"]),
            ),
        )


def delete_back_office_receipt_allocations_for_payment(conn, payment_id: int):
    ensure_back_office_receipt_schema(conn)
    conn.execute(
        "DELETE FROM back_office_receipt_allocations WHERE hotel_credit_payment_id = ?",
        (int(payment_id),),
    )


def list_back_office_receipts(
    conn, date_from: date, date_to: date, search: str = "", agency_id=None
) -> list[dict]:
    ensure_back_office_receipt_schema(conn)
    sql = """
        SELECT *
        FROM back_office_receipts
        WHERE receipt_date >= ? AND receipt_date <= ?
        """
    params = [date_from.isoformat(), date_to.isoformat()]
    if agency_id is not None:
        sql += " AND agency_id = ?"
        params.append(int(agency_id))
    sql += " ORDER BY receipt_date DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    items = [_receipt_dict(row) for row in rows]
    needle = (search or "").strip().lower()
    if not needle:
        return items
    filtered = []
    for item in items:
        blob = " ".join(
            [
                item["receipt_no"],
                item["payer_name"],
                item["payment_mode_label"],
                item["instrument_no"],
                item["towards"],
                item["amount_words"],
                f"{item['amount']:.2f}",
            ]
        ).lower()
        if needle in blob:
            filtered.append(item)
    return items if not needle else filtered


def _parse_agency_filter(args, agencies):
    """Return (selected_key, agency_id|None, label)."""
    raw = str(args.get("agency") or args.get("supplier") or "all").strip()
    if not raw or raw.lower() == "all":
        return "all", None, "All agencies"
    try:
        agency_id = int(raw)
    except (TypeError, ValueError):
        return "all", None, "All agencies"
    for agency in agencies or []:
        try:
            if int(agency.get("id")) == agency_id:
                return str(agency_id), agency_id, str(agency.get("name") or "Agency")
        except (TypeError, ValueError):
            continue
    return "all", None, "All agencies"


def list_back_office_receipt_filter_agencies(
    conn, date_from: date, date_to: date
) -> list[dict]:
    """Agencies that appear on receipt ledger rows in the date window."""
    ensure_back_office_receipt_schema(conn)
    ensure_hotel_invoice_credits_schema(conn)
    date_from_s = date_from.isoformat()
    date_to_s = date_to.isoformat()
    rows = conn.execute(
        """
        SELECT a.id, a.name, COALESCE(a.gst, '') AS gst
        FROM agencies a
        WHERE a.id IN (
            SELECT DISTINCT r.agency_id
            FROM back_office_receipts r
            WHERE r.agency_id IS NOT NULL
              AND r.receipt_date >= ? AND r.receipt_date <= ?
            UNION
            SELECT DISTINCT r.agency_id
            FROM back_office_receipt_allocations alloc
            JOIN hotel_invoice_credit_payments p
              ON p.id = alloc.hotel_credit_payment_id
            JOIN back_office_receipts r ON r.id = alloc.receipt_id
            WHERE r.agency_id IS NOT NULL
              AND p.payment_date >= ? AND p.payment_date <= ?
        )
        ORDER BY LOWER(a.name), a.id
        """,
        (date_from_s, date_to_s, date_from_s, date_to_s),
    ).fetchall()
    return [
        {
            "id": int(row["id"]),
            "name": row["name"] or "",
            "gst": row["gst"] or "",
        }
        for row in rows
    ]


def _ensure_selected_agency_in_filters(filter_agencies, selected_agency_id, agency_row):
    """Keep the active agency visible in the filter list when dates exclude it."""
    if selected_agency_id is None or not agency_row:
        return list(filter_agencies or [])
    items = list(filter_agencies or [])
    try:
        sid = int(selected_agency_id)
    except (TypeError, ValueError):
        return items
    for item in items:
        try:
            if int(item.get("id")) == sid:
                return items
        except (TypeError, ValueError):
            continue
    items.append(
        {
            "id": int(agency_row.get("id") or sid),
            "name": agency_row.get("name") or "Agency",
            "gst": agency_row.get("gst") or "",
        }
    )
    items.sort(key=lambda row: str(row.get("name") or "").lower())
    return items


BOR_LEDGER_ENTRY_RECEIPT = "receipt"
BOR_LEDGER_ENTRY_APPLIED = "applied"
BOR_LEDGER_ENTRY_LABELS = {
    BOR_LEDGER_ENTRY_RECEIPT: "Received",
    BOR_LEDGER_ENTRY_APPLIED: "Applied",
}


def list_back_office_receipt_ledger_entries(
    conn, date_from: date, date_to: date, search: str = "", agency_id=None
) -> list[dict]:
    """Unified ledger: receipt credits (+) and hotel-credit applications (−)."""
    ensure_back_office_receipt_schema(conn)
    ensure_hotel_invoice_credits_schema(conn)
    date_from_s = date_from.isoformat()
    date_to_s = date_to.isoformat()
    agency_id_int = None
    try:
        if agency_id is not None and str(agency_id).strip() not in ("", "all"):
            agency_id_int = int(agency_id)
    except (TypeError, ValueError):
        agency_id_int = None
    entries = []

    receipt_sql = """
        SELECT *
        FROM back_office_receipts
        WHERE receipt_date >= ? AND receipt_date <= ?
        """
    receipt_params = [date_from_s, date_to_s]
    if agency_id_int is not None:
        receipt_sql += " AND agency_id = ?"
        receipt_params.append(agency_id_int)
    receipt_sql += " ORDER BY receipt_date ASC, id ASC"
    receipt_rows = conn.execute(receipt_sql, receipt_params).fetchall()
    for row in receipt_rows:
        item = _receipt_dict(row)
        applied = round(back_office_receipt_applied_total(conn, item["id"]), 2)
        amount = round(float(item["amount"] or 0), 2)
        instrument = item["instrument_no"] or ""
        if item["instrument_date"]:
            instrument = (
                f"{instrument} · {item['instrument_date']}" if instrument else item["instrument_date"]
            )
        entries.append(
            {
                "id": f"r-{item['id']}",
                "entry_type": BOR_LEDGER_ENTRY_RECEIPT,
                "entry_date": item["receipt_date"],
                "receipt_id": item["id"],
                "allocation_id": None,
                "payment_id": None,
                "receipt_no": item["receipt_no"],
                "party_name": item["payer_name"],
                "payment_mode": item["payment_mode"],
                "payment_mode_label": item["payment_mode_label"],
                "instrument": instrument,
                "detail": item["towards"] or "Advance / receipt",
                "description": item["towards"] or "Back office receipt",
                "amount": amount,
                "signed_amount": amount,
                "amount_words": item["amount_words"],
                "can_edit": applied <= 0.009,
                "can_delete": applied <= 0.009,
                "agency_id": item["agency_id"],
                "instrument_no": item["instrument_no"],
                "instrument_date": item["instrument_date"] or "",
                "towards": item["towards"] or "",
                "sort_rank": 1,
            }
        )

    alloc_sql = """
        SELECT a.id AS allocation_id,
               a.receipt_id,
               a.hotel_credit_payment_id AS payment_id,
               a.amount AS applied_amount,
               p.payment_date,
               p.agency_name,
               r.receipt_no,
               r.payer_name,
               r.payment_mode,
               r.agency_id,
               (
                   SELECT GROUP_CONCAT(alloc.invoice_number, ', ')
                   FROM hotel_invoice_credit_payment_allocations alloc
                   WHERE alloc.payment_id = p.id
               ) AS invoice_numbers
        FROM back_office_receipt_allocations a
        JOIN hotel_invoice_credit_payments p ON p.id = a.hotel_credit_payment_id
        JOIN back_office_receipts r ON r.id = a.receipt_id
        WHERE p.payment_date >= ? AND p.payment_date <= ?
        """
    alloc_params = [date_from_s, date_to_s]
    if agency_id_int is not None:
        alloc_sql += " AND r.agency_id = ?"
        alloc_params.append(agency_id_int)
    alloc_sql += " ORDER BY p.payment_date ASC, a.id ASC"
    alloc_rows = conn.execute(alloc_sql, alloc_params).fetchall()
    for row in alloc_rows:
        amount = round(float(row["applied_amount"] or 0), 2)
        if amount <= 0.009:
            continue
        agency = str(row["agency_name"] or row["payer_name"] or "").strip()
        invoices = str(row["invoice_numbers"] or "").strip()
        detail = "Hotel credit clearance"
        if invoices:
            detail = f"Hotel credit · {invoices}"
        mode = (row["payment_mode"] or "cash") if row else "cash"
        entries.append(
            {
                "id": f"a-{int(row['allocation_id'])}",
                "entry_type": BOR_LEDGER_ENTRY_APPLIED,
                "entry_date": row["payment_date"] or "",
                "receipt_id": int(row["receipt_id"]),
                "allocation_id": int(row["allocation_id"]),
                "payment_id": int(row["payment_id"]),
                "receipt_no": row["receipt_no"] or "",
                "party_name": agency or "—",
                "payment_mode": mode,
                "payment_mode_label": PAYMENT_MODE_LABELS.get(mode, mode),
                "instrument": "",
                "detail": detail,
                "description": detail,
                "amount": amount,
                "signed_amount": -amount,
                "amount_words": "",
                "can_edit": False,
                "can_delete": False,
                "agency_id": row["agency_id"],
                "instrument_no": "",
                "instrument_date": "",
                "towards": "",
                "sort_rank": 2,
            }
        )

    inv_sql = """
        SELECT a.id AS allocation_id,
               a.receipt_id,
               a.amount AS applied_amount,
               a.hotel_invoice_number,
               COALESCE(substr(a.created_at, 1, 10), '') AS payment_date,
               r.receipt_no,
               r.payer_name,
               r.payment_mode,
               r.agency_id
        FROM back_office_receipt_allocations a
        JOIN back_office_receipts r ON r.id = a.receipt_id
        WHERE TRIM(COALESCE(a.hotel_invoice_number, '')) != ''
          AND a.hotel_credit_payment_id IS NULL
          AND COALESCE(substr(a.created_at, 1, 10), '') >= ?
          AND COALESCE(substr(a.created_at, 1, 10), '') <= ?
        """
    inv_params = [date_from_s, date_to_s]
    if agency_id_int is not None:
        inv_sql += " AND r.agency_id = ?"
        inv_params.append(agency_id_int)
    inv_sql += " ORDER BY payment_date ASC, a.id ASC"
    for row in conn.execute(inv_sql, inv_params).fetchall():
        amount = round(float(row["applied_amount"] or 0), 2)
        if amount <= 0.009:
            continue
        inv_no = str(row["hotel_invoice_number"] or "").strip()
        detail = f"Hotel invoice · {inv_no}" if inv_no else "Hotel invoice settle"
        mode = (row["payment_mode"] or "cash") if row else "cash"
        entries.append(
            {
                "id": f"ai-{int(row['allocation_id'])}",
                "entry_type": BOR_LEDGER_ENTRY_APPLIED,
                "entry_date": row["payment_date"] or "",
                "receipt_id": int(row["receipt_id"]),
                "allocation_id": int(row["allocation_id"]),
                "payment_id": None,
                "receipt_no": row["receipt_no"] or "",
                "party_name": str(row["payer_name"] or "").strip() or "—",
                "payment_mode": mode,
                "payment_mode_label": PAYMENT_MODE_LABELS.get(mode, mode),
                "instrument": "",
                "detail": detail,
                "description": detail,
                "amount": amount,
                "signed_amount": -amount,
                "amount_words": "",
                "can_edit": False,
                "can_delete": False,
                "agency_id": row["agency_id"],
                "instrument_no": "",
                "instrument_date": "",
                "towards": "",
                "sort_rank": 2,
            }
        )

    entries.sort(
        key=lambda row: (
            row.get("entry_date") or "",
            int(row.get("sort_rank") or 99),
            int(row.get("receipt_id") or 0),
            int(row.get("allocation_id") or 0),
        )
    )
    running = 0.0
    for entry in entries:
        running = round(running + float(entry.get("signed_amount") or 0), 2)
        entry["running_balance"] = running

    needle = (search or "").strip().lower()
    if needle:
        filtered = []
        for entry in entries:
            blob = " ".join(
                [
                    entry.get("entry_date") or "",
                    BOR_LEDGER_ENTRY_LABELS.get(entry["entry_type"], entry["entry_type"]),
                    entry.get("receipt_no") or "",
                    entry.get("party_name") or "",
                    entry.get("payment_mode") or "",
                    entry.get("payment_mode_label") or "",
                    entry.get("instrument") or "",
                    entry.get("instrument_no") or "",
                    entry.get("detail") or "",
                    entry.get("towards") or "",
                    entry.get("amount_words") or "",
                    f"{entry.get('amount') or 0:.2f}",
                    f"{entry.get('signed_amount') or 0:.2f}",
                    f"{entry.get('running_balance') or 0:.2f}",
                ]
            ).lower()
            if needle in blob:
                filtered.append(entry)
        entries = filtered

    # Newest first for display (balances already computed chronologically).
    entries.reverse()
    return entries


def back_office_receipt_ledger_totals(
    entries: list[dict], conn=None, date_from=None, date_to=None, agency_id=None
) -> dict:
    received = 0.0
    applied = 0.0
    receipt_count = 0
    applied_count = 0
    for entry in entries or []:
        amount = round(float(entry.get("amount") or 0), 2)
        if entry.get("entry_type") == BOR_LEDGER_ENTRY_RECEIPT:
            received += amount
            receipt_count += 1
        elif entry.get("entry_type") == BOR_LEDGER_ENTRY_APPLIED:
            applied += amount
            applied_count += 1
    received = round(received, 2)
    applied = round(applied, 2)
    # True remaining on receipts in the date window (not yet applied to hotel credit).
    balance = round(received - applied, 2)
    if conn is not None and date_from is not None and date_to is not None:
        pending = 0.0
        for row in list_back_office_receipts(
            conn, date_from, date_to, agency_id=agency_id
        ):
            used = back_office_receipt_applied_total(conn, row["id"])
            left = round(float(row["amount"] or 0) - used, 2)
            if left > 0.009:
                pending += left
        balance = round(pending, 2)
    return {
        "received_total": received,
        "applied_total": applied,
        "balance_total": balance,
        "receipt_count": receipt_count,
        "applied_count": applied_count,
        "entry_count": len(entries or []),
    }

def _validated_receipt_fields(
    conn,
    *,
    payer_name: str,
    agency_id,
    amount: float,
    payment_mode: str,
    instrument_no: str = "",
    instrument_date: date | None = None,
    towards: str = "",
):
    mode = _normalize_payment_mode(payment_mode)
    if not mode:
        raise ValueError("Select a valid payment mode.")
    name = (payer_name or "").strip()
    agency = None
    if agency_id not in (None, "", 0, "0"):
        agency = get_agency(conn, agency_id)
        if not agency:
            raise ValueError("Selected agency was not found.")
        if not name:
            name = (agency.get("name") or "").strip()
    if not name:
        raise ValueError("Enter who the amount was received from.")
    if amount <= 0:
        raise ValueError("Enter a positive amount.")
    if mode == "cash":
        instrument_no = ""
        instrument_date = None
    elif mode != "cash" and not (instrument_no or "").strip():
        raise ValueError("Enter cheque / draft / UTR number.")
    return {
        "payer_name": name[:200],
        "agency_id": int(agency["id"]) if agency else None,
        "amount": float(amount),
        "amount_words": amount_in_indian_words(amount),
        "payment_mode": mode,
        "instrument_no": (instrument_no or "").strip()[:80],
        "instrument_date": instrument_date.isoformat() if instrument_date else None,
        "towards": (towards or "").strip()[:300],
    }


def create_back_office_receipt(
    conn,
    *,
    receipt_date: date,
    payer_name: str,
    agency_id,
    amount: float,
    payment_mode: str,
    instrument_no: str = "",
    instrument_date: date | None = None,
    towards: str = "",
    user_id=None,
) -> dict:
    ensure_back_office_receipt_schema(conn)
    fields = _validated_receipt_fields(
        conn,
        payer_name=payer_name,
        agency_id=agency_id,
        amount=amount,
        payment_mode=payment_mode,
        instrument_no=instrument_no,
        instrument_date=instrument_date,
        towards=towards,
    )
    short_fy, seq, receipt_no = allocate_back_office_receipt_no(conn, receipt_date)
    cur = conn.execute(
        """
        INSERT INTO back_office_receipts
          (receipt_no, fiscal_year, seq, receipt_date, payer_name, agency_id,
           amount, amount_words, payment_mode, instrument_no, instrument_date,
           towards, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            receipt_no,
            short_fy,
            seq,
            receipt_date.isoformat(),
            fields["payer_name"],
            fields["agency_id"],
            fields["amount"],
            fields["amount_words"],
            fields["payment_mode"],
            fields["instrument_no"],
            fields["instrument_date"],
            fields["towards"],
            user_id,
        ),
    )
    row = conn.execute(
        "SELECT * FROM back_office_receipts WHERE id = ?",
        (cur.lastrowid,),
    ).fetchone()
    return _receipt_dict(row)


def update_back_office_receipt(
    conn,
    receipt_id: int,
    *,
    receipt_date: date,
    payer_name: str,
    agency_id,
    amount: float,
    payment_mode: str,
    instrument_no: str = "",
    instrument_date: date | None = None,
    towards: str = "",
) -> dict:
    ensure_back_office_receipt_schema(conn)
    existing = conn.execute(
        "SELECT id FROM back_office_receipts WHERE id = ?",
        (int(receipt_id),),
    ).fetchone()
    if not existing:
        raise ValueError("Receipt not found.")
    applied = back_office_receipt_applied_total(conn, receipt_id)
    if applied > 0.009:
        raise ValueError(
            "Cannot edit a receipt that has been applied to hotel credit. "
            "Revert the hotel credit payment first."
        )
    fields = _validated_receipt_fields(
        conn,
        payer_name=payer_name,
        agency_id=agency_id,
        amount=amount,
        payment_mode=payment_mode,
        instrument_no=instrument_no,
        instrument_date=instrument_date,
        towards=towards,
    )
    conn.execute(
        """
        UPDATE back_office_receipts
           SET receipt_date = ?,
               payer_name = ?,
               agency_id = ?,
               amount = ?,
               amount_words = ?,
               payment_mode = ?,
               instrument_no = ?,
               instrument_date = ?,
               towards = ?
         WHERE id = ?
        """,
        (
            receipt_date.isoformat(),
            fields["payer_name"],
            fields["agency_id"],
            fields["amount"],
            fields["amount_words"],
            fields["payment_mode"],
            fields["instrument_no"],
            fields["instrument_date"],
            fields["towards"],
            int(receipt_id),
        ),
    )
    row = conn.execute(
        "SELECT * FROM back_office_receipts WHERE id = ?",
        (int(receipt_id),),
    ).fetchone()
    return _receipt_dict(row)


def delete_back_office_receipt(conn, receipt_id: int) -> bool:
    ensure_back_office_receipt_schema(conn)
    applied = back_office_receipt_applied_total(conn, receipt_id)
    if applied > 0.009:
        raise ValueError(
            "Cannot delete a receipt that has been applied to hotel credit. "
            "Revert the hotel credit payment first."
        )
    cur = conn.execute(
        "DELETE FROM back_office_receipts WHERE id = ?",
        (int(receipt_id),),
    )
    return cur.rowcount > 0


def _resolve_date_range(args):
    """Return (date_from, date_to, active). Default: Indian FY start → today."""
    raw_from = (args.get("date_from") or "").strip()
    raw_to = (args.get("date_to") or "").strip()
    today = date.today()
    fy_start, _ = indian_fiscal_year_bounds(today)
    if not raw_from and not raw_to:
        return fy_start, today, True
    date_from = _parse_iso_date(raw_from, fallback=fy_start) or fy_start
    date_to = _parse_iso_date(raw_to, fallback=today) or today
    if date_from > date_to:
        date_from, date_to = date_to, date_from
    return date_from, date_to, True

def register_back_office_receipt(app, *, pop_auth_notice, get_user):
    _bind_helpers(pop_auth_notice=pop_auth_notice, get_user=get_user)

    @app.route("/accounts/back-office-receipt")
    def back_office_receipt():
        today = date.today()
        date_from, date_to, date_filter_active = _resolve_date_range(request.args)
        search = (request.args.get("q") or request.args.get("search") or "").strip()
        conn = get_db()
        try:
            agencies = list_agencies(conn)
            selected_agency, agency_id, selected_agency_label = _parse_agency_filter(
                request.args, agencies
            )
            filter_agencies = list_back_office_receipt_filter_agencies(
                conn, date_from, date_to
            )
            if agency_id is not None:
                filter_agencies = _ensure_selected_agency_in_filters(
                    filter_agencies, agency_id, get_agency(conn, agency_id)
                )
            ledger_entries = list_back_office_receipt_ledger_entries(
                conn,
                date_from,
                date_to,
                search=search,
                agency_id=agency_id,
            )
            totals = back_office_receipt_ledger_totals(
                ledger_entries,
                conn=conn,
                date_from=date_from,
                date_to=date_to,
                agency_id=agency_id,
            )
        finally:
            conn.close()
        report_kwargs = {
            "date_from": date_from.isoformat(),
            "date_to": date_to.isoformat(),
        }
        if selected_agency and selected_agency != "all":
            report_kwargs["agency"] = selected_agency
        if search:
            report_kwargs["q"] = search
        return render_template(
            "back_office_receipt.html",
            auth_notice=_pop_auth_notice() if _pop_auth_notice else None,
            page_title="Back Office Receipt",
            ledger_entries=ledger_entries,
            receipts=ledger_entries,  # backward-compatible alias for older JS hooks
            agencies=agencies,
            filter_agencies=filter_agencies,
            selected_agency=selected_agency,
            selected_agency_label=selected_agency_label,
            payment_modes=PAYMENT_MODES,
            bor_entry_labels=BOR_LEDGER_ENTRY_LABELS,
            receipt_count=totals["receipt_count"],
            applied_count=totals["applied_count"],
            entry_count=totals["entry_count"],
            total_amount=totals["received_total"],
            applied_total=totals["applied_total"],
            balance_total=totals["balance_total"],
            date_from=date_from.isoformat(),
            date_to=date_to.isoformat(),
            date_filter_active=True,
            search_q=search,
            filter_form_action=url_for("back_office_receipt"),
            clear_url=url_for("back_office_receipt"),
            report_url=url_for("export_back_office_receipt_report", **report_kwargs),
            add_url=url_for("back_office_receipt_add"),
            edit_url=url_for("back_office_receipt_edit"),
            delete_url=url_for("back_office_receipt_delete"),
            today_iso=today.isoformat(),
            de_nav_section="accounts",
            de_nav_accounts_view="back_office_receipt",
        )

    @app.route("/accounts/back-office-receipt/add", methods=["POST"])
    def back_office_receipt_add():
        data = request.get_json(silent=True) or {}
        receipt_date = _parse_iso_date(data.get("receipt_date") or data.get("date"))
        if not receipt_date:
            receipt_date = date.today()
        if receipt_date > date.today():
            return jsonify({"ok": False, "error": "Receipt date cannot be in the future."}), 400
        amount = _parse_money(data.get("amount"))
        mode = _normalize_payment_mode(data.get("payment_mode") or data.get("mode"))
        instrument_date = _parse_iso_date(data.get("instrument_date"))
        user = _get_user() if _get_user else None
        user_id = user.get("id") if user else None
        conn = get_db()
        try:
            receipt = create_back_office_receipt(
                conn,
                receipt_date=receipt_date,
                payer_name=data.get("payer_name") or data.get("received_from") or "",
                agency_id=data.get("agency_id"),
                amount=amount,
                payment_mode=mode,
                instrument_no=data.get("instrument_no") or data.get("cheque_no") or "",
                instrument_date=instrument_date,
                towards=data.get("towards") or "",
                user_id=user_id,
            )
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            return jsonify({"ok": False, "error": str(exc)}), 400
        finally:
            conn.close()
        return jsonify({"ok": True, "receipt": receipt})

    @app.route("/accounts/back-office-receipt/edit", methods=["POST"])
    def back_office_receipt_edit():
        data = request.get_json(silent=True) or {}
        try:
            receipt_id = int(data.get("id") or data.get("receipt_id") or 0)
        except (TypeError, ValueError):
            receipt_id = 0
        if receipt_id <= 0:
            return jsonify({"ok": False, "error": "Receipt not found."}), 404
        receipt_date = _parse_iso_date(data.get("receipt_date") or data.get("date"))
        if not receipt_date:
            receipt_date = date.today()
        if receipt_date > date.today():
            return jsonify({"ok": False, "error": "Receipt date cannot be in the future."}), 400
        amount = _parse_money(data.get("amount"))
        mode = _normalize_payment_mode(data.get("payment_mode") or data.get("mode"))
        instrument_date = _parse_iso_date(data.get("instrument_date"))
        conn = get_db()
        try:
            receipt = update_back_office_receipt(
                conn,
                receipt_id,
                receipt_date=receipt_date,
                payer_name=data.get("payer_name") or data.get("received_from") or "",
                agency_id=data.get("agency_id"),
                amount=amount,
                payment_mode=mode,
                instrument_no=data.get("instrument_no") or data.get("cheque_no") or "",
                instrument_date=instrument_date,
                towards=data.get("towards") or "",
            )
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            status = 404 if "not found" in str(exc).lower() else 400
            return jsonify({"ok": False, "error": str(exc)}), status
        finally:
            conn.close()
        return jsonify({"ok": True, "receipt": receipt})

    @app.route("/accounts/back-office-receipt/delete", methods=["POST"])
    def back_office_receipt_delete():
        data = request.get_json(silent=True) or {}
        try:
            receipt_id = int(data.get("id") or data.get("receipt_id") or 0)
        except (TypeError, ValueError):
            receipt_id = 0
        if receipt_id <= 0:
            return jsonify({"ok": False, "error": "Receipt not found."}), 404
        conn = get_db()
        try:
            deleted = delete_back_office_receipt(conn, receipt_id)
            if not deleted:
                return jsonify({"ok": False, "error": "Receipt not found."}), 404
            conn.commit()
        except ValueError as exc:
            conn.rollback()
            return jsonify({"ok": False, "error": str(exc)}), 400
        finally:
            conn.close()
        return jsonify({"ok": True, "id": receipt_id})

    @app.route("/accounts/back-office-receipt/report")
    def export_back_office_receipt_report():
        from openpyxl import Workbook
        from openpyxl.styles import Font

        date_from, date_to, _active = _resolve_date_range(request.args)
        search = (request.args.get("q") or request.args.get("search") or "").strip()
        conn = get_db()
        try:
            agencies = list_agencies(conn)
            _selected, agency_id, _label = _parse_agency_filter(request.args, agencies)
            ledger_entries = list_back_office_receipt_ledger_entries(
                conn, date_from, date_to, search=search, agency_id=agency_id
            )
        finally:
            conn.close()

        wb = Workbook()
        ws = wb.active
        ws.title = "Back Office Receipt"
        headers = [
            "Date",
            "Type",
            "Receipt No.",
            "Party",
            "Mode",
            "Instrument",
            "Detail",
            "Amount",
            "Balance",
        ]
        ws.append(headers)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        # Export chronological (oldest first) for readable running balance.
        for item in reversed(ledger_entries):
            ws.append(
                [
                    item.get("entry_date") or "",
                    BOR_LEDGER_ENTRY_LABELS.get(
                        item.get("entry_type"), item.get("entry_type")
                    ),
                    item.get("receipt_no") or "",
                    item.get("party_name") or "",
                    item.get("payment_mode_label") or "",
                    item.get("instrument") or "",
                    item.get("detail") or "",
                    item.get("signed_amount"),
                    item.get("running_balance"),
                ]
            )
        import io

        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        fname = (
            f"Hotel Bell Elite Back Office Receipt "
            f"{date_from.strftime('%d %B %y')} to {date_to.strftime('%d %B %y')}.xlsx"
        )
        return send_file(
            buf,
            as_attachment=True,
            download_name=fname,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
