import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, timedelta

import auth_security

DATABASE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bell_elite.db")
SQL_NOW = "datetime('now','localtime')"

_POS_LIQUOR_CATEGORY_RE = re.compile(
    r"\b(liquou?r|alcohol|whisky|whiskey|beer|wine|vodka|gin|rum|brandy|"
    r"spirit|spirits|imfl|cocktail|cocktails|shots?|scotch|tequila|"
    r"champagne|cider|liqueur|aperitif)\b",
    re.IGNORECASE,
)


def is_pos_liquor_category(name):
    """True when a POS menu category is treated as liquor (VAT 10%)."""
    return bool(_POS_LIQUOR_CATEGORY_RE.search(str(name or "").strip()))


class _RequestScopedConnection:
    """sqlite3 connection reused for one Flask request.

    close() is a no-op so nested helpers can get_db()/close() without
    dropping the caller's transaction. close_request_db() closes the file
    at request teardown.
    """

    __slots__ = ("_raw",)

    def __init__(self, conn):
        object.__setattr__(self, "_raw", conn)

    def close(self):
        # Nested get_db()/close() is common in helpers. Rolling back here
        # would undo the caller's uncommitted work on the shared connection.
        # The real close happens in close_request_db() at request teardown.
        return None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        raw = object.__getattribute__(self, "_raw")
        if exc_type:
            raw.rollback()
        else:
            try:
                raw.commit()
            except sqlite3.Error:
                raw.rollback()
                raise
        return False

    def __getattr__(self, name):
        return getattr(object.__getattribute__(self, "_raw"), name)

    def __setattr__(self, name, value):
        setattr(object.__getattribute__(self, "_raw"), name, value)


def _connect():
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-8192")
    conn.execute("PRAGMA mmap_size=67108864")
    return conn


def get_db():
    """Return a SQLite connection.

    Inside a Flask app context the same connection is reused for the request.
    Outside Flask (tests, scripts, init) a new connection is opened.
    """
    try:
        from flask import g, has_app_context
    except ImportError:
        return _connect()
    if has_app_context():
        wrapper = getattr(g, "_hbe_db", None)
        if wrapper is None:
            wrapper = _RequestScopedConnection(_connect())
            g._hbe_db = wrapper
        return wrapper
    return _connect()


def close_request_db(exc=None):
    """Close the request-scoped connection (Flask teardown_appcontext)."""
    try:
        from flask import g, has_app_context
    except ImportError:
        return
    if not has_app_context():
        return
    wrapper = getattr(g, "_hbe_db", None)
    if wrapper is None:
        return
    try:
        delattr(g, "_hbe_db")
    except Exception:
        g._hbe_db = None
    raw = getattr(wrapper, "_raw", wrapper)
    try:
        raw.close()
    except Exception:
        pass


# POS workspace outlets (path/nav keys). Distinct from Sales Update OUTLET_* labels.
POS_OUTLET_RESTAURANT = "restaurant"
POS_OUTLET_BAR = "bar"
POS_OUTLETS = (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR)


def normalize_pos_outlet(value):
    """Return restaurant|bar; unknown/empty → restaurant."""
    key = str(value or "").strip().lower()
    if key in ("bar",):
        return POS_OUTLET_BAR
    return POS_OUTLET_RESTAURANT


_SPC_FY_ORDER_RE = re.compile(r"^SPC/(\d{2}-\d{2})/(\d+)$", re.IGNORECASE)
_SPC_NILL_FY_ORDER_RE = re.compile(r"^SPC/(\d{2}-\d{2})/Nill/(\d+)$", re.IGNORECASE)
_SPC_LEGACY_LONG_FY_ORDER_RE = re.compile(r"^SPC/(\d+)/(\d{4}-\d{2})$", re.IGNORECASE)
_SPC_LEGACY_ORDER_RE = re.compile(r"^SPC/(\d+)$", re.IGNORECASE)
_KOT_SPC_FY_RE = re.compile(r"^KOT/SPC/(\d{2}-\d{2})/(\d+)$", re.IGNORECASE)
_KOT_INV_FY_RE = re.compile(r"^KOT/INV/(\d{2}-\d{2})/(\d+)$", re.IGNORECASE)
_INV_FY_ORDER_RE = re.compile(r"^INV/(\d{2}-\d{2})/(\d+)$", re.IGNORECASE)
_INV_NILL_FY_ORDER_RE = re.compile(r"^INV/(\d{2}-\d{2})/Nill/(\d+)$", re.IGNORECASE)
_INV_LEGACY_LONG_FY_ORDER_RE = re.compile(r"^INV/(\d+)/(\d{4}-\d{2})$", re.IGNORECASE)
_INV_LEGACY_ORDER_RE = re.compile(r"^INV/(\d+)$", re.IGNORECASE)
_POS_NIL_TAX_EPS = 0.005


def _coerce_calendar_date(value=None):
    """Normalize value to a date (default: local today)."""
    if value is None:
        return datetime.now().date()
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and hasattr(value, "month") and not isinstance(value, str):
        return value
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            return datetime.now().date()
    return datetime.now().date()


def indian_fiscal_year_label(value=None):
    """Indian FY label (Apr–Mar), e.g. 2026-07-29 → '2026-27'."""
    d = _coerce_calendar_date(value)
    if d.month >= 4:
        start_year = d.year
    else:
        start_year = d.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def indian_fiscal_year_short_label(value=None):
    """Short Indian FY label, e.g. 2026-07-29 → '26-27' (or '2026-27' → '26-27')."""
    text = str(value or "").strip()
    if re.match(r"^\d{4}-\d{2}$", text):
        start, end = text.split("-", 1)
        return f"{start[-2:]}-{end[-2:]}"
    if re.match(r"^\d{2}-\d{2}$", text):
        return text
    fy = indian_fiscal_year_label(value)
    parts = fy.split("-")
    if len(parts) == 2:
        return f"{parts[0][-2:]}-{parts[1][-2:]}"
    return fy


def indian_fiscal_year_bounds(value=None):
    """Return (fy_start, reference_date) for Indian FY Apr–Mar.

    fy_start is 1 Apr of the FY containing the reference day. The second value
    is that reference day (typically today for filter chip defaults).
    """
    d = _coerce_calendar_date(value)
    if d.month >= 4:
        start_year = d.year
    else:
        start_year = d.year - 1
    return date(start_year, 4, 1), d


def is_restaurant_spc_order_no(order_no, fiscal_year=None):
    """True when order_no is SPC/{yy-yy}/{n} (optionally matching a specific FY)."""
    match = _SPC_FY_ORDER_RE.match(str(order_no or "").strip())
    if not match:
        return False
    if fiscal_year and match.group(1) != indian_fiscal_year_short_label(fiscal_year):
        return False
    return True


def is_restaurant_spc_nill_order_no(order_no, fiscal_year=None):
    """True when order_no is SPC/{yy-yy}/Nill/{n} (optionally matching a specific FY)."""
    match = _SPC_NILL_FY_ORDER_RE.match(str(order_no or "").strip())
    if not match:
        return False
    if fiscal_year and match.group(1) != indian_fiscal_year_short_label(fiscal_year):
        return False
    return True


def is_bar_inv_order_no(order_no, fiscal_year=None):
    """True when order_no is INV/{yy-yy}/{n} (optionally matching a specific FY)."""
    match = _INV_FY_ORDER_RE.match(str(order_no or "").strip())
    if not match:
        return False
    if fiscal_year and match.group(1) != indian_fiscal_year_short_label(fiscal_year):
        return False
    return True


def is_bar_inv_nill_order_no(order_no, fiscal_year=None):
    """True when order_no is INV/{yy-yy}/Nill/{n} (optionally matching a specific FY)."""
    match = _INV_NILL_FY_ORDER_RE.match(str(order_no or "").strip())
    if not match:
        return False
    if fiscal_year and match.group(1) != indian_fiscal_year_short_label(fiscal_year):
        return False
    return True


def pos_invoice_is_nil_tax(gst_amount, vat_amount):
    """True when CGST+UGST and VAT amounts are all ~0."""
    try:
        gst = float(gst_amount or 0)
    except (TypeError, ValueError):
        gst = 0.0
    try:
        vat = float(vat_amount or 0)
    except (TypeError, ValueError):
        vat = 0.0
    if gst != gst:
        gst = 0.0
    if vat != vat:
        vat = 0.0
    return gst <= _POS_NIL_TAX_EPS and vat <= _POS_NIL_TAX_EPS


def is_provisional_pos_order_no(order_no, outlet=None):
    """Client placeholders replaced only when Generate Invoice (customerBill) runs."""
    text = str(order_no or "").strip()
    if not text:
        return True
    outlet_key = normalize_pos_outlet(outlet) if outlet is not None else None
    upper = text.upper()
    # Offline-local drafts (ORD-L-…) become SPC|INV/{yy-yy}/{n} on Generate Invoice.
    if upper.startswith("ORD-L-"):
        return True
    # Offline drafts: PREFIX/{token}/{fy}; numeric PREFIX/{yy-yy}/{n} is final.
    # PREFIX/{yy-yy}/Nill/{n} is the nil-tax official series.
    # Also treat legacy PREFIX/{n}/{YYYY-YY} client drafts / wrong series as provisional
    # so they are re-minted into the new PREFIX/{yy-yy}/{n} format.
    if (
        upper.startswith("SPC/")
        and not is_restaurant_spc_order_no(text)
        and not is_restaurant_spc_nill_order_no(text)
    ):
        if outlet_key in (None, POS_OUTLET_RESTAURANT):
            return bool(
                re.match(r"^SPC/[^/]+/\d{2}-\d{2}$", text, re.IGNORECASE)
                or re.match(r"^SPC/[^/]+/\d{4}-\d{2}$", text, re.IGNORECASE)
                or _SPC_LEGACY_LONG_FY_ORDER_RE.match(text)
                or _SPC_LEGACY_ORDER_RE.match(text)
            )
    if (
        upper.startswith("INV/")
        and not is_bar_inv_order_no(text)
        and not is_bar_inv_nill_order_no(text)
    ):
        if outlet_key in (None, POS_OUTLET_BAR):
            return bool(
                re.match(r"^INV/[^/]+/\d{2}-\d{2}$", text, re.IGNORECASE)
                or re.match(r"^INV/[^/]+/\d{4}-\d{2}$", text, re.IGNORECASE)
                or _INV_LEGACY_LONG_FY_ORDER_RE.match(text)
                or _INV_LEGACY_ORDER_RE.match(text)
            )
    return False


def _pos_is_official_order_no(order_no, outlet=None):
    """True when order_no is a final SPC|INV/{yy-yy}/[{Nill}/]{n} series number."""
    text = str(order_no or "").strip()
    if not text:
        return False
    return (
        is_restaurant_spc_order_no(text)
        or is_restaurant_spc_nill_order_no(text)
        or is_bar_inv_order_no(text)
        or is_bar_inv_nill_order_no(text)
    )


def _pos_order_no_taken(conn, order_no, *, outlet=None, ignore_invoice_id=None):
    """True when any invoice row already owns this order number."""
    text = str(order_no or "").strip()
    if not text:
        return False
    params = [text]
    sql = "SELECT id FROM pos_invoices WHERE order_no = ?"
    if outlet is not None:
        sql += " AND outlet = ?"
        params.append(normalize_pos_outlet(outlet))
    row = conn.execute(sql + " LIMIT 1", params).fetchone()
    if not row:
        return False
    if ignore_invoice_id is not None and int(row["id"]) == int(ignore_invoice_id):
        return False
    return True


def mint_provisional_pos_order_no(outlet=None, order_date=None, conn=None):
    """Server-side draft order number: PREFIX/{hex}/{yy-yy} until Generate Invoice."""
    short_fy = indian_fiscal_year_short_label(order_date)
    suffix = secrets.token_hex(3).upper()
    outlet_key = normalize_pos_outlet(outlet)
    brand = (
        POS_DEFAULT_BAR_INVOICE_PREFIX
        if outlet_key == POS_OUTLET_BAR
        else POS_DEFAULT_RESTAURANT_INVOICE_PREFIX
    )
    if conn is not None:
        try:
            brand = pos_invoice_prefix_brand(conn, outlet_key)
        except Exception:
            pass
    return f"{brand}/{suffix}/{short_fy}"


_POS_INVOICE_PREFIX_WITH_SEQ_RE = re.compile(
    r"^(?P<stem>.+?)/(?P<fy>\d{2}-\d{2})/(?P<seq>\d+)$",
    re.IGNORECASE,
)
_POS_INVOICE_PREFIX_FY_ONLY_RE = re.compile(
    r"^(?P<stem>.+?)/(?P<fy>\d{2}-\d{2})$",
    re.IGNORECASE,
)
POS_DEFAULT_RESTAURANT_INVOICE_PREFIX = "SPC"
POS_DEFAULT_BAR_INVOICE_PREFIX = "INV"


def _normalize_pos_invoice_prefix(prefix, default):
    """Trim and strip trailing slashes; fall back to default when empty."""
    text = str(prefix or "").strip()
    while text.endswith("/"):
        text = text[:-1].rstrip()
    return text or str(default or "").strip() or "SPC"


def _pos_settings_text_field(values, named_key, legacy_index=None):
    """Read a text setting value (named key, else optional legacy fN)."""
    if not isinstance(values, dict):
        return None
    field = values.get(named_key)
    if field is None and legacy_index is not None:
        field = values.get(f"f{int(legacy_index)}")
    if field is None:
        return None
    if isinstance(field, dict):
        return field.get("value")
    return field


def parse_pos_invoice_prefix_setting(raw, default="SPC"):
    """Parse settings Prefix into (stem, embedded_fy|None, next_seq_floor|None).

    Accepts:
      SPC
      SPC/26-27/
      SPC/26-27/726   → stem SPC/26-27, floor 726
    """
    default = _normalize_pos_invoice_prefix(default, "SPC")
    text = _normalize_pos_invoice_prefix(raw, default)
    match = _POS_INVOICE_PREFIX_WITH_SEQ_RE.match(text)
    if match:
        stem = _normalize_pos_invoice_prefix(
            f"{match.group('stem')}/{match.group('fy')}", default
        )
        try:
            floor = int(match.group("seq"))
        except (TypeError, ValueError):
            floor = None
        return stem, match.group("fy"), floor
    match = _POS_INVOICE_PREFIX_FY_ONLY_RE.match(text)
    if match:
        return text, match.group("fy"), None
    return text, None, None


def pos_invoice_prefix_parts(conn, outlet=POS_OUTLET_RESTAURANT):
    """Return (stem, embedded_fy, next_seq_floor) for the outlet invoice series."""
    outlet = normalize_pos_outlet(outlet)
    default = (
        POS_DEFAULT_BAR_INVOICE_PREFIX
        if outlet == POS_OUTLET_BAR
        else POS_DEFAULT_RESTAURANT_INVOICE_PREFIX
    )
    settings = get_pos_restaurant_settings(conn, outlet)
    values = _pos_settings_panel_values(settings, "invoice")
    # Prefer named key; fall back to legacy auto-key f0 from the Numbering card.
    raw = _pos_settings_text_field(values, "invoice_prefix", legacy_index=0)
    return parse_pos_invoice_prefix_setting(raw, default)


def pos_invoice_prefix(conn, outlet=POS_OUTLET_RESTAURANT):
    """Series stem from POS Settings → Invoice → Prefix."""
    stem, _fy, _floor = pos_invoice_prefix_parts(conn, outlet)
    return stem


def pos_invoice_prefix_brand(conn, outlet=POS_OUTLET_RESTAURANT):
    """First path segment of the invoice prefix (e.g. SPC from SPC/26-27)."""
    stem = pos_invoice_prefix(conn, outlet)
    brand = str(stem or "").split("/", 1)[0].strip().upper()
    outlet = normalize_pos_outlet(outlet)
    if brand:
        return brand
    return (
        POS_DEFAULT_BAR_INVOICE_PREFIX
        if outlet == POS_OUTLET_BAR
        else POS_DEFAULT_RESTAURANT_INVOICE_PREFIX
    )


def _pos_invoice_fy_order_re(stem, embedded_fy=None):
    """Compile matcher for PREFIX/{yy-yy}/{n} or PREFIX_WITH_FY/{n}."""
    stem = _normalize_pos_invoice_prefix(stem, "SPC")
    escaped = re.escape(stem)
    if embedded_fy:
        return re.compile(rf"^{escaped}/(\d+)$", re.IGNORECASE), 1, None
    return re.compile(rf"^{escaped}/(\d{{2}}-\d{{2}})/(\d+)$", re.IGNORECASE), 1, 2


def _pos_invoice_nill_order_re(stem, embedded_fy=None):
    """Compile matcher for PREFIX/{yy-yy}/Nill/{n} or PREFIX_WITH_FY/Nill/{n}."""
    stem = _normalize_pos_invoice_prefix(stem, "SPC")
    escaped = re.escape(stem)
    if embedded_fy:
        return re.compile(rf"^{escaped}/Nill/(\d+)$", re.IGNORECASE), 1, None
    return re.compile(rf"^{escaped}/(\d{{2}}-\d{{2}})/Nill/(\d+)$", re.IGNORECASE), 1, 2


def format_pos_invoice_order_no(stem, short_fy, seq, *, nil_tax=False, embedded_fy=None):
    """Build official POS order number from settings stem + FY + sequence."""
    stem = _normalize_pos_invoice_prefix(stem, "SPC")
    try:
        seq_n = int(seq)
    except (TypeError, ValueError):
        seq_n = 0
    fy = str(embedded_fy or short_fy or "").strip() or indian_fiscal_year_short_label()
    if embedded_fy:
        if nil_tax:
            return f"{stem}/Nill/{seq_n}"
        return f"{stem}/{seq_n}"
    if nil_tax:
        return f"{stem}/{fy}/Nill/{seq_n}"
    return f"{stem}/{fy}/{seq_n}"


def _next_prefixed_invoice_seq(
    conn,
    outlet,
    prefix,
    fy_re,
    legacy_long_fy_re,
    legacy_re,
    fiscal_year,
    *,
    fy_group=1,
    seq_group=2,
    min_seq=1,
):
    """Next numeric sequence for PREFIX/{yy-yy}/{n} within an outlet + FY.

    Only the new PREFIX/{yy-yy}/{n} series is counted. Legacy PREFIX/{n}/{YYYY-YY}
    numbers must not advance this series (otherwise seq jumps to 100000+).
    Returns the smallest unused positive integer so the series can start at 1
    even if a bad high number was minted earlier.
    When min_seq is set (from settings like SPC/26-27/726), allocation starts there.
    """
    short_fy = indian_fiscal_year_short_label(fiscal_year)
    prefix = str(prefix or "").strip().upper()
    try:
        floor = max(1, int(min_seq or 1))
    except (TypeError, ValueError):
        floor = 1
    used = set()
    rows = conn.execute(
        """
        SELECT order_no
        FROM pos_invoices
        WHERE outlet = ?
          AND upper(order_no) LIKE ?
        """,
        (normalize_pos_outlet(outlet), f"{prefix}/%"),
    ).fetchall()
    for row in rows:
        order_no = str(row["order_no"] or "").strip()
        match = fy_re.match(order_no) if fy_re is not None else None
        if not match:
            continue
        try:
            if seq_group is None:
                # Embedded-FY form: PREFIX/yy-yy/{n} → only one capture group.
                used.add(int(match.group(fy_group)))
            else:
                if match.group(fy_group) != short_fy:
                    continue
                used.add(int(match.group(seq_group)))
        except (TypeError, ValueError, IndexError):
            pass
    n = floor
    while n in used:
        n += 1
    return n


def next_restaurant_invoice_seq(conn, fiscal_year, prefix=None, min_seq=1, embedded_fy=None):
    """Next sequence for Restaurant within the given FY (settings-driven prefix)."""
    stem = _normalize_pos_invoice_prefix(
        prefix if prefix is not None else POS_DEFAULT_RESTAURANT_INVOICE_PREFIX,
        POS_DEFAULT_RESTAURANT_INVOICE_PREFIX,
    )
    if prefix is None and embedded_fy is None:
        stem, embedded_fy, floor = pos_invoice_prefix_parts(conn, POS_OUTLET_RESTAURANT)
        if min_seq == 1 and floor:
            min_seq = floor
    fy_re, fy_group, seq_group = _pos_invoice_fy_order_re(stem, embedded_fy)
    return _next_prefixed_invoice_seq(
        conn,
        POS_OUTLET_RESTAURANT,
        stem,
        fy_re,
        _SPC_LEGACY_LONG_FY_ORDER_RE,
        _SPC_LEGACY_ORDER_RE,
        fiscal_year if not embedded_fy else embedded_fy,
        fy_group=fy_group,
        seq_group=seq_group,
        min_seq=min_seq,
    )


def next_restaurant_nill_invoice_seq(conn, fiscal_year, prefix=None, min_seq=1, embedded_fy=None):
    """Next Nill sequence for Restaurant within the given FY."""
    stem = _normalize_pos_invoice_prefix(
        prefix if prefix is not None else POS_DEFAULT_RESTAURANT_INVOICE_PREFIX,
        POS_DEFAULT_RESTAURANT_INVOICE_PREFIX,
    )
    if prefix is None and embedded_fy is None:
        stem, embedded_fy, floor = pos_invoice_prefix_parts(conn, POS_OUTLET_RESTAURANT)
        if min_seq == 1 and floor:
            min_seq = floor
    fy_re, fy_group, seq_group = _pos_invoice_nill_order_re(stem, embedded_fy)
    return _next_prefixed_invoice_seq(
        conn,
        POS_OUTLET_RESTAURANT,
        stem,
        fy_re,
        _SPC_LEGACY_LONG_FY_ORDER_RE,
        _SPC_LEGACY_ORDER_RE,
        fiscal_year if not embedded_fy else embedded_fy,
        fy_group=fy_group,
        seq_group=seq_group,
        min_seq=min_seq,
    )


def next_bar_invoice_seq(conn, fiscal_year, prefix=None, min_seq=1, embedded_fy=None):
    """Next sequence for Bar within the given FY (settings-driven prefix)."""
    stem = _normalize_pos_invoice_prefix(
        prefix if prefix is not None else POS_DEFAULT_BAR_INVOICE_PREFIX,
        POS_DEFAULT_BAR_INVOICE_PREFIX,
    )
    if prefix is None and embedded_fy is None:
        stem, embedded_fy, floor = pos_invoice_prefix_parts(conn, POS_OUTLET_BAR)
        if min_seq == 1 and floor:
            min_seq = floor
    fy_re, fy_group, seq_group = _pos_invoice_fy_order_re(stem, embedded_fy)
    return _next_prefixed_invoice_seq(
        conn,
        POS_OUTLET_BAR,
        stem,
        fy_re,
        _INV_LEGACY_LONG_FY_ORDER_RE,
        _INV_LEGACY_ORDER_RE,
        fiscal_year if not embedded_fy else embedded_fy,
        fy_group=fy_group,
        seq_group=seq_group,
        min_seq=min_seq,
    )


def next_bar_nill_invoice_seq(conn, fiscal_year, prefix=None, min_seq=1, embedded_fy=None):
    """Next Nill sequence for Bar within the given FY."""
    stem = _normalize_pos_invoice_prefix(
        prefix if prefix is not None else POS_DEFAULT_BAR_INVOICE_PREFIX,
        POS_DEFAULT_BAR_INVOICE_PREFIX,
    )
    if prefix is None and embedded_fy is None:
        stem, embedded_fy, floor = pos_invoice_prefix_parts(conn, POS_OUTLET_BAR)
        if min_seq == 1 and floor:
            min_seq = floor
    fy_re, fy_group, seq_group = _pos_invoice_nill_order_re(stem, embedded_fy)
    return _next_prefixed_invoice_seq(
        conn,
        POS_OUTLET_BAR,
        stem,
        fy_re,
        _INV_LEGACY_LONG_FY_ORDER_RE,
        _INV_LEGACY_ORDER_RE,
        fiscal_year if not embedded_fy else embedded_fy,
        fy_group=fy_group,
        seq_group=seq_group,
        min_seq=min_seq,
    )


def allocate_pos_restaurant_order_no(conn, order_date=None, nil_tax=False):
    """Allocate settings-driven PREFIX/{yy-yy}/{n} (or …/Nill/{n}) for Restaurant."""
    stem, embedded_fy, floor = pos_invoice_prefix_parts(conn, POS_OUTLET_RESTAURANT)
    fy = indian_fiscal_year_label(order_date)
    short_fy = embedded_fy or indian_fiscal_year_short_label(fy)
    min_seq = floor or 1
    for _ in range(10000):
        if nil_tax:
            seq = next_restaurant_nill_invoice_seq(
                conn, fy, prefix=stem, min_seq=min_seq, embedded_fy=embedded_fy
            )
        else:
            seq = next_restaurant_invoice_seq(
                conn, fy, prefix=stem, min_seq=min_seq, embedded_fy=embedded_fy
            )
        candidate = format_pos_invoice_order_no(
            stem, short_fy, seq, nil_tax=nil_tax, embedded_fy=embedded_fy
        )
        if not _pos_order_no_taken(conn, candidate, outlet=POS_OUTLET_RESTAURANT):
            return candidate
        min_seq = seq + 1
    raise ValueError("Unable to allocate a restaurant invoice number.")


def allocate_pos_bar_order_no(conn, order_date=None, nil_tax=False):
    """Allocate settings-driven PREFIX/{yy-yy}/{n} (or …/Nill/{n}) for Bar."""
    stem, embedded_fy, floor = pos_invoice_prefix_parts(conn, POS_OUTLET_BAR)
    fy = indian_fiscal_year_label(order_date)
    short_fy = embedded_fy or indian_fiscal_year_short_label(fy)
    min_seq = floor or 1
    for _ in range(10000):
        if nil_tax:
            seq = next_bar_nill_invoice_seq(
                conn, fy, prefix=stem, min_seq=min_seq, embedded_fy=embedded_fy
            )
        else:
            seq = next_bar_invoice_seq(
                conn, fy, prefix=stem, min_seq=min_seq, embedded_fy=embedded_fy
            )
        candidate = format_pos_invoice_order_no(
            stem, short_fy, seq, nil_tax=nil_tax, embedded_fy=embedded_fy
        )
        if not _pos_order_no_taken(conn, candidate, outlet=POS_OUTLET_BAR):
            return candidate
        min_seq = seq + 1
    raise ValueError("Unable to allocate a bar invoice number.")


def pos_kot_display_no(order_no, kot_no=""):
    """Kitchen token display number: prefer stored series, else KOT/… from order_no.

    Official series is KOT/SPC/{yy-yy}/{n} (Restaurant) or KOT/INV/{yy-yy}/{n} (Bar).
    Legacy ORD- / KOT- prefixes are normalized to KOT/.
    """
    stored = " ".join(str(kot_no or "").split()).strip()
    if stored:
        return stored
    text = " ".join(str(order_no or "").split()).strip()
    if not text:
        return ""
    upper = text.upper()
    if upper.startswith("KOT/"):
        return text
    if upper.startswith("KOT-"):
        return "KOT/" + text[4:]
    if upper.startswith("ORD-"):
        return "KOT/" + text[4:]
    return "KOT/" + text


def _next_pos_kot_seq(conn, brand, fiscal_year):
    """Next unused n for KOT/{brand}/{yy-yy}/{n}."""
    short_fy = indian_fiscal_year_short_label(fiscal_year)
    brand = str(brand or "SPC").strip().upper() or "SPC"
    fy_re = _KOT_INV_FY_RE if brand == "INV" else _KOT_SPC_FY_RE
    used = set()
    rows = conn.execute(
        """
        SELECT kot_no
        FROM pos_invoices
        WHERE upper(TRIM(COALESCE(kot_no, ''))) LIKE ?
        """,
        (f"KOT/{brand}/%",),
    ).fetchall()
    for row in rows:
        value = str(row["kot_no"] or "").strip()
        match = fy_re.match(value)
        if match and match.group(1) == short_fy:
            try:
                used.add(int(match.group(2)))
            except (TypeError, ValueError):
                pass
    n = 1
    while n in used:
        n += 1
    return n


def allocate_pos_kot_no(conn, outlet=None, order_date=None):
    """Allocate KOT/SPC|{INV}/{yy-yy}/{n} for the first kitchen send."""
    outlet_norm = normalize_pos_outlet(outlet)
    brand = "INV" if outlet_norm == POS_OUTLET_BAR else "SPC"
    fy = indian_fiscal_year_label(order_date)
    short_fy = indian_fiscal_year_short_label(fy)
    for _ in range(10000):
        seq = _next_pos_kot_seq(conn, brand, fy)
        candidate = f"KOT/{brand}/{short_fy}/{seq}"
        taken = conn.execute(
            """
            SELECT id FROM pos_invoices
            WHERE upper(TRIM(COALESCE(kot_no, ''))) = upper(?)
            LIMIT 1
            """,
            (candidate,),
        ).fetchone()
        if not taken:
            return candidate
    raise ValueError("Unable to allocate a kitchen order token number.")


def ensure_pos_invoice_kot_no(conn, invoice_id, *, outlet=None, order_date=None):
    """Persist a KOT series number on first kitchen send (idempotent)."""
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        """
        SELECT kot_no, outlet, order_date, order_no, first_kot_at
        FROM pos_invoices
        WHERE id = ?
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    existing = " ".join(str(row["kot_no"] or "").split()).strip()
    if existing:
        return existing
    keys = row.keys()
    use_outlet = outlet
    if use_outlet is None and "outlet" in keys:
        use_outlet = row["outlet"]
    use_date = order_date
    if use_date is None and "order_date" in keys:
        use_date = row["order_date"] or None
    kot_no = allocate_pos_kot_no(conn, outlet=use_outlet, order_date=use_date)
    conn.execute(
        f"""
        UPDATE pos_invoices
        SET kot_no = ?,
            updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (kot_no, invoice_id),
    )
    return kot_no


def resolve_pos_outlets(outlet=None, outlets=None):
    """Return a unique tuple of restaurant|bar outlets for list queries."""
    if outlets is not None:
        if isinstance(outlets, (str, bytes)):
            raw = [outlets]
        else:
            try:
                raw = list(outlets)
            except TypeError:
                raw = [outlets]
        resolved = []
        seen = set()
        for value in raw:
            key = normalize_pos_outlet(value)
            if key in seen:
                continue
            seen.add(key)
            resolved.append(key)
        if resolved:
            return tuple(resolved)
    return (normalize_pos_outlet(outlet),)


def empty_pos_floor_payload():
    """Empty floor layout when nothing is saved yet."""
    return {"areas": [], "tables": []}


def _normalize_pos_floor_payload(areas, tables):
    """Return a lean, validated floor payload (areas + tables)."""
    clean_areas = []
    seen_area = set()
    for raw in areas or []:
        if not isinstance(raw, dict):
            continue
        area_id = str(raw.get("id") or "").strip()
        name = str(raw.get("name") or "").strip() or "Area"
        if not area_id or area_id in seen_area:
            continue
        seen_area.add(area_id)
        clean_areas.append({"id": area_id, "type": "area", "name": name})

    clean_tables = []
    seen_table = set()
    for raw in tables or []:
        if not isinstance(raw, dict):
            continue
        table_id = str(raw.get("id") or "").strip()
        if not table_id or table_id in seen_table:
            continue
        seen_table.add(table_id)
        seats = raw.get("seats", 2)
        try:
            seats = max(1, int(seats))
        except (TypeError, ValueError):
            seats = 2
        shape = str(raw.get("shape") or "square").strip() or "square"
        status = str(raw.get("status") or "available").strip() or "available"
        area_id = raw.get("areaId")
        if area_id is not None:
            area_id = str(area_id).strip() or None
        merge_group_id = str(raw.get("mergeGroupId") or "").strip() or None
        merge_primary = bool(raw.get("mergePrimary")) if merge_group_id else False
        clean_tables.append(
            {
                "id": table_id,
                "type": "table",
                "name": str(raw.get("name") or "").strip() or table_id,
                "seats": seats,
                "shape": shape,
                "status": status,
                "areaId": area_id,
                "mergeGroupId": merge_group_id,
                "mergePrimary": merge_primary,
            }
        )
    return {"areas": clean_areas, "tables": clean_tables}


def default_bar_pos_floor_payload():
    """Bar Tables 1–16 (4 seats) + Counter Chairs 1–6 (1 seat) from venue sheet."""
    areas = [
        {"id": "bar_tables", "type": "area", "name": "Tables"},
        {"id": "bar_counter", "type": "area", "name": "Counter"},
    ]
    tables = []
    for i in range(1, 17):
        tables.append(
            {
                "id": f"bar_t{i}",
                "type": "table",
                "name": f"Table {i}",
                "seats": 4,
                "shape": "square",
                "status": "available",
                "areaId": "bar_tables",
                "mergeGroupId": None,
                "mergePrimary": False,
            }
        )
    for i in range(1, 7):
        tables.append(
            {
                "id": f"bar_c{i}",
                "type": "table",
                "name": f"Chair {i}",
                "seats": 1,
                "shape": "square",
                "status": "available",
                "areaId": "bar_counter",
                "mergeGroupId": None,
                "mergePrimary": False,
            }
        )
    return _normalize_pos_floor_payload(areas, tables)


def ensure_pos_schema(conn):
    """Create lean POS floor, settings, and menu tables (soft migration)."""
    cursor = conn.cursor()
    # --- Floor layout: migrate singleton id=1 → outlet-keyed rows ---
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pos_floor_layout'"
    )
    if not cursor.fetchone():
        cursor.execute(
            """
            CREATE TABLE pos_floor_layout (
                outlet     TEXT    NOT NULL PRIMARY KEY,
                payload    TEXT    NOT NULL,
                updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
    else:
        floor_cols = {
            row[1] for row in cursor.execute("PRAGMA table_info(pos_floor_layout)").fetchall()
        }
        if "outlet" not in floor_cols:
            cursor.execute("ALTER TABLE pos_floor_layout RENAME TO pos_floor_layout_legacy")
            cursor.execute(
                """
                CREATE TABLE pos_floor_layout (
                    outlet     TEXT    NOT NULL PRIMARY KEY,
                    payload    TEXT    NOT NULL,
                    updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO pos_floor_layout (outlet, payload, updated_at)
                SELECT ?, payload, COALESCE(NULLIF(updated_at, ''), datetime('now','localtime'))
                FROM pos_floor_layout_legacy
                """,
                (POS_OUTLET_RESTAURANT,),
            )
            cursor.execute("DROP TABLE pos_floor_layout_legacy")

    # --- Settings: same outlet migration ---
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='pos_restaurant_settings'"
    )
    if not cursor.fetchone():
        cursor.execute(
            """
            CREATE TABLE pos_restaurant_settings (
                outlet     TEXT    NOT NULL PRIMARY KEY,
                payload    TEXT    NOT NULL DEFAULT '{}',
                updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
            )
            """
        )
    else:
        settings_cols = {
            row[1]
            for row in cursor.execute("PRAGMA table_info(pos_restaurant_settings)").fetchall()
        }
        if "outlet" not in settings_cols:
            cursor.execute(
                "ALTER TABLE pos_restaurant_settings RENAME TO pos_restaurant_settings_legacy"
            )
            cursor.execute(
                """
                CREATE TABLE pos_restaurant_settings (
                    outlet     TEXT    NOT NULL PRIMARY KEY,
                    payload    TEXT    NOT NULL DEFAULT '{}',
                    updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO pos_restaurant_settings (outlet, payload, updated_at)
                SELECT ?, payload, COALESCE(NULLIF(updated_at, ''), datetime('now','localtime'))
                FROM pos_restaurant_settings_legacy
                """,
                (POS_OUTLET_RESTAURANT,),
            )
            cursor.execute("DROP TABLE pos_restaurant_settings_legacy")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_menu_categories (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            sort_order  INTEGER NOT NULL DEFAULT 0,
            is_visible  INTEGER NOT NULL DEFAULT 1,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_menu_items (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id   INTEGER NOT NULL,
            product_id    INTEGER,
            name          TEXT    NOT NULL,
            code          TEXT    NOT NULL DEFAULT '',
            barcode       TEXT    NOT NULL DEFAULT '',
            variant       TEXT    NOT NULL DEFAULT '',
            rate          REAL    NOT NULL DEFAULT 0,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (category_id) REFERENCES pos_menu_categories(id)
        )
        """
    )
    item_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_menu_items)").fetchall()
    }
    if "product_id" not in item_cols:
        cursor.execute("ALTER TABLE pos_menu_items ADD COLUMN product_id INTEGER")
    _pos_menu_item_extra_cols = {
        "menu_type": "TEXT NOT NULL DEFAULT ''",
        "item_kind": "TEXT NOT NULL DEFAULT 'food'",
        "portion_size": "TEXT NOT NULL DEFAULT ''",
        "prep_time_mins": "INTEGER",
        "shelf_life": "TEXT NOT NULL DEFAULT ''",
        "notes": "TEXT NOT NULL DEFAULT ''",
        "target_margin_pct": "REAL",
        "updated_by": "TEXT NOT NULL DEFAULT ''",
    }
    for col_name, col_ddl in _pos_menu_item_extra_cols.items():
        if col_name not in item_cols:
            cursor.execute(f"ALTER TABLE pos_menu_items ADD COLUMN {col_name} {col_ddl}")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_items_category
        ON pos_menu_items(category_id, is_active)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_items_product
        ON pos_menu_items(product_id, is_active)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_menu_recipe_lines (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_item_id  INTEGER NOT NULL,
            product_id    INTEGER NOT NULL,
            qty           REAL    NOT NULL,
            unit          TEXT    NOT NULL DEFAULT 'g',
            sort_order    INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY (menu_item_id) REFERENCES pos_menu_items(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_recipe_item
        ON pos_menu_recipe_lines(menu_item_id, sort_order)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_menu_price_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            menu_item_id  INTEGER NOT NULL,
            old_price     REAL    NOT NULL,
            new_price     REAL    NOT NULL,
            reason        TEXT    NOT NULL DEFAULT '',
            updated_by    TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (menu_item_id) REFERENCES pos_menu_items(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_price_history_item
        ON pos_menu_price_history(menu_item_id, created_at DESC, id DESC)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_invoices (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            order_no         TEXT    NOT NULL,
            saved_at         TEXT    NOT NULL,
            order_date       TEXT    NOT NULL,
            order_type       TEXT    NOT NULL DEFAULT 'dine_in',
            table_label      TEXT    NOT NULL DEFAULT '',
            captain          TEXT    NOT NULL DEFAULT '',
            customer_name    TEXT    NOT NULL DEFAULT '',
            customer_mobile  TEXT    NOT NULL DEFAULT '',
            notes            TEXT    NOT NULL DEFAULT '',
            discount_type    TEXT    NOT NULL DEFAULT 'pct',
            discount_value   REAL    NOT NULL DEFAULT 0,
            service_type     TEXT    NOT NULL DEFAULT 'pct',
            service_value    REAL    NOT NULL DEFAULT 0,
            tip_amount       REAL    NOT NULL DEFAULT 0,
            coupon_code      TEXT    NOT NULL DEFAULT '',
            subtotal         REAL    NOT NULL DEFAULT 0,
            discount_amount  REAL    NOT NULL DEFAULT 0,
            gst_amount       REAL    NOT NULL DEFAULT 0,
            service_amount   REAL    NOT NULL DEFAULT 0,
            tip              REAL    NOT NULL DEFAULT 0,
            round_off        REAL    NOT NULL DEFAULT 0,
            grand_total      REAL    NOT NULL DEFAULT 0,
            created_by       TEXT    NOT NULL DEFAULT '',
            is_active        INTEGER NOT NULL DEFAULT 1,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_pos_invoices_order_no
        ON pos_invoices(order_no)
        WHERE is_active = 1
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoices_date
        ON pos_invoices(order_date, is_active)
        """
    )
    invoice_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_invoices)").fetchall()
    }
    # Bill lifecycle ('open' -> 'closed') and KOT tracking — occupancy flips when a
    # dine-in bill with a table is saved (items on the table); closing frees it.
    if "status" not in invoice_cols:
        cursor.execute("ALTER TABLE pos_invoices ADD COLUMN status TEXT NOT NULL DEFAULT 'open'")
    if "kot_sent" not in invoice_cols:
        cursor.execute("ALTER TABLE pos_invoices ADD COLUMN kot_sent INTEGER NOT NULL DEFAULT 0")
    if "first_kot_at" not in invoice_cols:
        cursor.execute("ALTER TABLE pos_invoices ADD COLUMN first_kot_at TEXT NOT NULL DEFAULT ''")
    if "kot_no" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN kot_no TEXT NOT NULL DEFAULT ''"
        )
    if "customer_bill_sent" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN customer_bill_sent INTEGER NOT NULL DEFAULT 0"
        )
    if "customer_bill_at" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN customer_bill_at TEXT NOT NULL DEFAULT ''"
        )
    # Idempotency marker: stock was reduced once for this closed invoice (POS sale).
    if "stock_deducted_at" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN stock_deducted_at TEXT NOT NULL DEFAULT ''"
        )
    if "vat_amount" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN vat_amount REAL NOT NULL DEFAULT 0"
        )
    if "discount_line_uids" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN discount_line_uids TEXT NOT NULL DEFAULT ''"
        )
    if "discount_reason" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN discount_reason TEXT NOT NULL DEFAULT ''"
        )
    if "cancel_reason" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT ''"
        )
    if "cancelled_at" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN cancelled_at TEXT NOT NULL DEFAULT ''"
        )
    if "cancelled_by" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN cancelled_by TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoices_table_open
        ON pos_invoices(table_label, status, order_type, is_active)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_invoice_lines (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id    INTEGER NOT NULL,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            menu_item_id  INTEGER,
            name          TEXT    NOT NULL DEFAULT '',
            variant       TEXT    NOT NULL DEFAULT '',
            rate          REAL    NOT NULL DEFAULT 0,
            qty           REAL    NOT NULL DEFAULT 0,
            line_total    REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (invoice_id) REFERENCES pos_invoices(id)
        )
        """
    )
    line_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_invoice_lines)").fetchall()
    }
    if "sent_qty" not in line_cols:
        cursor.execute("ALTER TABLE pos_invoice_lines ADD COLUMN sent_qty REAL NOT NULL DEFAULT 0")
    if "notes" not in line_cols:
        cursor.execute(
            "ALTER TABLE pos_invoice_lines ADD COLUMN notes TEXT NOT NULL DEFAULT ''"
        )
    if "line_uid" not in line_cols:
        cursor.execute(
            "ALTER TABLE pos_invoice_lines ADD COLUMN line_uid TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoice_lines_invoice
        ON pos_invoice_lines(invoice_id, sort_order)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS pos_invoice_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_id      INTEGER NOT NULL,
            payment_date    TEXT    NOT NULL,
            payment_method  TEXT    NOT NULL,
            amount          REAL    NOT NULL DEFAULT 0,
            transaction_id  TEXT    NOT NULL DEFAULT '',
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (invoice_id) REFERENCES pos_invoices(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoice_payments_invoice
        ON pos_invoice_payments(invoice_id, id)
        """
    )
    invoice_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_invoices)").fetchall()
    }
    if "payment_notes" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN payment_notes TEXT NOT NULL DEFAULT ''"
        )
    if "settled_at" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN settled_at TEXT NOT NULL DEFAULT ''"
        )

    # Outlet columns (default restaurant for existing rows)
    cat_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_menu_categories)").fetchall()
    }
    if "outlet" not in cat_cols:
        cursor.execute(
            "ALTER TABLE pos_menu_categories ADD COLUMN outlet TEXT NOT NULL DEFAULT 'restaurant'"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_categories_outlet
        ON pos_menu_categories(outlet, is_active, sort_order)
        """
    )
    item_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_menu_items)").fetchall()
    }
    if "outlet" not in item_cols:
        cursor.execute(
            "ALTER TABLE pos_menu_items ADD COLUMN outlet TEXT NOT NULL DEFAULT 'restaurant'"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_menu_items_outlet
        ON pos_menu_items(outlet, category_id, is_active)
        """
    )
    invoice_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(pos_invoices)").fetchall()
    }
    if "outlet" not in invoice_cols:
        cursor.execute(
            "ALTER TABLE pos_invoices ADD COLUMN outlet TEXT NOT NULL DEFAULT 'restaurant'"
        )
    if "tax_cgst_pct" not in invoice_cols:
        cursor.execute("ALTER TABLE pos_invoices ADD COLUMN tax_cgst_pct REAL")
    if "tax_ugst_pct" not in invoice_cols:
        cursor.execute("ALTER TABLE pos_invoices ADD COLUMN tax_ugst_pct REAL")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoices_outlet_table_open
        ON pos_invoices(outlet, table_label, status, order_type, is_active)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_pos_invoices_outlet_date
        ON pos_invoices(outlet, order_date, is_active)
        """
    )

    # Seed Bar floor once (never overwrite a saved Bar layout)
    bar_row = cursor.execute(
        "SELECT outlet FROM pos_floor_layout WHERE outlet = ?",
        (POS_OUTLET_BAR,),
    ).fetchone()
    if not bar_row:
        bar_payload = default_bar_pos_floor_payload()
        blob = json.dumps(bar_payload, separators=(",", ":"))
        cursor.execute(
            f"""
            INSERT INTO pos_floor_layout (outlet, payload, updated_at)
            VALUES (?, ?, {SQL_NOW})
            """,
            (POS_OUTLET_BAR, blob),
        )
        cursor.execute(
            f"""
            INSERT OR IGNORE INTO pos_restaurant_settings (outlet, payload, updated_at)
            VALUES (?, '{{}}', {SQL_NOW})
            """,
            (POS_OUTLET_BAR,),
        )

    ensure_customers_schema(conn)
    conn.commit()


def _normalize_customer_mobile(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())[:10]


def _normalize_customer_first_name(value):
    return " ".join(str(value or "").split()).strip()


def _normalize_customer_address(value):
    return " ".join(str(value or "").split()).strip()


def _normalize_customer_email(value):
    return " ".join(str(value or "").split()).strip().lower()


def _customer_row_field(row, key, default=""):
    try:
        return row[key] or default
    except (KeyError, IndexError, TypeError):
        return default


def ensure_customers_schema(conn):
    """Customer Master table shared with POS Customer Details (unique mobile)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS customers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name  TEXT    NOT NULL DEFAULT '',
            mobile      TEXT    NOT NULL DEFAULT '',
            email       TEXT    NOT NULL DEFAULT '',
            address     TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(customers)").fetchall()
    }
    if "address" not in cols:
        cursor.execute(
            "ALTER TABLE customers ADD COLUMN address TEXT NOT NULL DEFAULT ''"
        )
    if "email" not in cols:
        cursor.execute(
            "ALTER TABLE customers ADD COLUMN email TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_customers_mobile_unique
        ON customers(mobile) WHERE mobile != ''
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_customers_name
        ON customers(LOWER(first_name))
        """
    )
    _backfill_customers_from_invoices(conn)


def _backfill_customers_from_invoices(conn):
    """Seed Customer Master once from existing POS invoices (latest name per mobile)."""
    try:
        count_row = conn.execute("SELECT COUNT(*) AS n FROM customers").fetchone()
        if count_row and int(count_row["n"] if isinstance(count_row, dict) else count_row[0]):
            return
        # Prefer the most recent invoice name for each mobile.
        rows = conn.execute(
            """
            SELECT customer_mobile, customer_name
            FROM pos_invoices
            WHERE TRIM(COALESCE(customer_mobile, '')) != ''
              AND is_active = 1
            ORDER BY id DESC
            """
        ).fetchall()
    except Exception:
        return

    seen = set()
    for row in rows:
        mobile = _normalize_customer_mobile(row["customer_mobile"] if row else "")
        if len(mobile) != 10 or mobile in seen:
            continue
        seen.add(mobile)
        first_name = _normalize_customer_first_name(
            row["customer_name"] if row else ""
        ) or "Guest"
        try:
            conn.execute(
                f"""
                INSERT INTO customers (first_name, mobile, created_at, updated_at)
                VALUES (?, ?, {SQL_NOW}, {SQL_NOW})
                """,
                (first_name, mobile),
            )
        except Exception:
            continue


def customer_row_to_dict(row):
    if not row:
        return None
    return {
        "id": row["id"],
        "first_name": row["first_name"] or "",
        "name": row["first_name"] or "",  # POS autocomplete expects .name
        "mobile": row["mobile"] or "",
        "email": _customer_row_field(row, "email"),
        "address": _customer_row_field(row, "address"),
    }


def list_customers(conn):
    ensure_customers_schema(conn)
    rows = conn.execute(
        """
        SELECT id, first_name, mobile, email, address
        FROM customers
        ORDER BY LOWER(first_name), mobile, id
        """
    ).fetchall()
    return [customer_row_to_dict(row) for row in rows]


def get_customer(conn, customer_id):
    ensure_customers_schema(conn)
    if not customer_id:
        return None
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        "SELECT id, first_name, mobile, email, address FROM customers WHERE id = ?",
        (customer_id,),
    ).fetchone()
    return customer_row_to_dict(row)


def search_customers(conn, query, limit=8):
    """Match by mobile digits prefix or first-name contains."""
    ensure_customers_schema(conn)
    q = str(query or "").strip()
    digits = _normalize_customer_mobile(q)
    name_q = _normalize_customer_first_name(q).lower()
    if len(digits) < 2 and len(name_q) < 2:
        return []
    try:
        limit = max(1, min(int(limit), 20))
    except (TypeError, ValueError):
        limit = 8

    if len(digits) >= 2:
        rows = conn.execute(
            """
            SELECT id, first_name, mobile, email, address
            FROM customers
            WHERE mobile != '' AND mobile LIKE ?
            ORDER BY mobile ASC, LOWER(first_name) ASC, id ASC
            LIMIT ?
            """,
            (digits + "%", limit),
        ).fetchall()
        return [customer_row_to_dict(row) for row in rows]

    rows = conn.execute(
        """
        SELECT id, first_name, mobile, email, address
        FROM customers
        WHERE LOWER(first_name) LIKE ?
        ORDER BY LOWER(first_name) ASC, mobile ASC, id ASC
        LIMIT ?
        """,
        ("%" + name_q + "%", limit),
    ).fetchall()
    return [customer_row_to_dict(row) for row in rows]


def upsert_customer(conn, first_name, mobile, address="", email=""):
    """Create or update Customer Master from POS (requires 10-digit mobile).

    Unique by normalized mobile. If the mobile already exists, update first name
    when a new name is provided (or fill when the stored name is blank). Incomplete
    mobiles are ignored so partial POS input does not create junk rows.
    """
    ensure_customers_schema(conn)
    mobile = _normalize_customer_mobile(mobile)
    first_name = _normalize_customer_first_name(first_name)
    address = _normalize_customer_address(address)
    email = _normalize_customer_email(email)
    if len(mobile) != 10:
        return None

    existing = conn.execute(
        "SELECT id, first_name, mobile, email, address FROM customers WHERE mobile = ?",
        (mobile,),
    ).fetchone()
    if existing:
        existing_name = _normalize_customer_first_name(existing["first_name"])
        existing_address = _normalize_customer_address(
            _customer_row_field(existing, "address")
        )
        existing_email = _normalize_customer_email(
            _customer_row_field(existing, "email")
        )
        # Update / fill only when POS supplies a name that should replace blank or prior.
        next_name = first_name if first_name and first_name != existing_name else existing_name
        next_address = address if address and address != existing_address else existing_address
        next_email = email if email and email != existing_email else existing_email
        if (
            next_name != existing_name
            or next_address != existing_address
            or next_email != existing_email
        ):
            conn.execute(
                f"""
                UPDATE customers
                SET first_name = ?, email = ?, address = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (next_name or existing_name, next_email, next_address, existing["id"]),
            )
        return get_customer(conn, existing["id"])

    if not first_name:
        first_name = "Guest"
    cursor = conn.execute(
        f"""
        INSERT INTO customers (first_name, mobile, email, address, created_at, updated_at)
        VALUES (?, ?, ?, ?, {SQL_NOW}, {SQL_NOW})
        """,
        (first_name, mobile, email, address),
    )
    return get_customer(conn, cursor.lastrowid)


def save_customer_record(conn, first_name, mobile, customer_id=None, address="", email=""):
    """Insert/update Customer Master. Returns (saved_id, errors)."""
    ensure_customers_schema(conn)
    first_name = _normalize_customer_first_name(first_name)
    mobile = _normalize_customer_mobile(mobile)
    address = _normalize_customer_address(address)
    email = _normalize_customer_email(email)
    errors = []
    if not first_name:
        errors.append("First name is required.")
    if not mobile:
        errors.append("Mobile number is required.")
    elif len(mobile) != 10:
        errors.append("Mobile number must be a 10-digit number.")
    else:
        existing = conn.execute(
            "SELECT id FROM customers WHERE mobile = ?",
            (mobile,),
        ).fetchone()
        if existing and (customer_id is None or int(existing["id"]) != int(customer_id)):
            errors.append("A customer with this mobile number already exists.")
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        errors.append("Enter a valid email address.")
    if errors:
        return None, errors

    if customer_id:
        conn.execute(
            f"""
            UPDATE customers
            SET first_name = ?, mobile = ?, email = ?, address = ?, updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (first_name, mobile, email, address, customer_id),
        )
        return customer_id, []

    cursor = conn.execute(
        f"""
        INSERT INTO customers (first_name, mobile, email, address, created_at, updated_at)
        VALUES (?, ?, ?, ?, {SQL_NOW}, {SQL_NOW})
        """,
        (first_name, mobile, email, address),
    )
    return int(cursor.lastrowid), []


def delete_customer_record(conn, customer_id):
    ensure_customers_schema(conn)
    try:
        customer_id = int(customer_id)
    except (TypeError, ValueError):
        return False
    cursor = conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    return cursor.rowcount > 0


def ensure_agencies_schema(conn):
    """Agency Master for hotel travel/corporate agencies."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS agencies (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            name                 TEXT    NOT NULL DEFAULT '',
            phone                TEXT    NOT NULL DEFAULT '',
            gst                  TEXT    NOT NULL DEFAULT '',
            address              TEXT    NOT NULL DEFAULT '',
            bank_account_number  TEXT    NOT NULL DEFAULT '',
            bank_name            TEXT    NOT NULL DEFAULT '',
            ifsc_code            TEXT    NOT NULL DEFAULT '',
            created_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    existing_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(agencies)").fetchall()
    }
    for col, ddl in (
        ("phone", "TEXT NOT NULL DEFAULT ''"),
        ("bank_account_number", "TEXT NOT NULL DEFAULT ''"),
        ("bank_name", "TEXT NOT NULL DEFAULT ''"),
        ("ifsc_code", "TEXT NOT NULL DEFAULT ''"),
    ):
        if col not in existing_cols:
            cursor.execute(f"ALTER TABLE agencies ADD COLUMN {col} {ddl}")
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_agencies_name
        ON agencies(LOWER(name))
        """
    )


def _normalize_agency_name(value):
    return " ".join(str(value or "").split()).strip()


_GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def _normalize_agency_gst(value):
    return "".join(str(value or "").split()).upper()


def is_valid_agency_gst(value):
    """Empty is allowed; non-empty must be a 15-character GSTIN."""
    gst = _normalize_agency_gst(value)
    return (not gst) or bool(_GSTIN_RE.fullmatch(gst))


def _normalize_agency_phone(value):
    return "".join(str(value or "").split())


def _normalize_agency_bank_account(value):
    return "".join(str(value or "").split())


def _normalize_agency_bank_name(value):
    return " ".join(str(value or "").split()).strip()


def _normalize_agency_ifsc(value):
    return "".join(str(value or "").split()).upper()


def is_valid_agency_ifsc(value):
    """Empty is allowed; non-empty must be a standard 11-character IFSC."""
    ifsc = _normalize_agency_ifsc(value)
    return (not ifsc) or bool(_IFSC_RE.fullmatch(ifsc))


def sanitize_agency_gst_for_import(value):
    """Normalize GSTIN for migration imports.

    Strips labels like ``GST `` / ``GST:`` and returns a valid 15-char GSTIN,
    or ``""`` when missing/invalid (never aborts the agency upsert).
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper.startswith("GSTIN"):
        raw = raw[5:].lstrip(" :#-")
    elif upper.startswith("GST"):
        raw = raw[3:].lstrip(" :#-")
    gst = _normalize_agency_gst(raw)
    if gst and _GSTIN_RE.fullmatch(gst):
        return gst
    return ""


def upsert_agency_for_import(conn, name, gst="", address=""):
    """Upsert agency for data migration — invalid GST is dropped, not fatal."""
    return upsert_agency_by_name(
        conn,
        name,
        sanitize_agency_gst_for_import(gst),
        address,
    )


def _normalize_agency_address(value):
    return " ".join(str(value or "").split()).strip()


def agency_row_to_dict(row):
    if not row:
        return None
    keys = set(row.keys())
    return {
        "id": row["id"],
        "name": row["name"] or "",
        "phone": (row["phone"] or "") if "phone" in keys else "",
        "gst": row["gst"] or "",
        "address": row["address"] or "",
        "bank_account_number": (row["bank_account_number"] or "") if "bank_account_number" in keys else "",
        "bank_name": (row["bank_name"] or "") if "bank_name" in keys else "",
        "ifsc_code": (row["ifsc_code"] or "") if "ifsc_code" in keys else "",
    }


def list_agencies(conn):
    ensure_agencies_schema(conn)
    rows = conn.execute(
        """
        SELECT id, name, phone, gst, address, bank_account_number, bank_name, ifsc_code
        FROM agencies
        ORDER BY LOWER(name), id
        """
    ).fetchall()
    return [agency_row_to_dict(row) for row in rows]


def get_agency(conn, agency_id):
    ensure_agencies_schema(conn)
    if not agency_id:
        return None
    try:
        agency_id = int(agency_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        """
        SELECT id, name, phone, gst, address, bank_account_number, bank_name, ifsc_code
        FROM agencies WHERE id = ?
        """,
        (agency_id,),
    ).fetchone()
    return agency_row_to_dict(row)


def save_agency_record(
    conn,
    name,
    gst="",
    address="",
    agency_id=None,
    *,
    phone="",
    bank_account_number="",
    bank_name="",
    ifsc_code="",
):
    """Insert/update Agency Master. Returns (saved_id, errors)."""
    ensure_agencies_schema(conn)
    name = _normalize_agency_name(name)
    phone = _normalize_agency_phone(phone)
    gst = _normalize_agency_gst(gst)
    address = _normalize_agency_address(address)
    bank_account_number = _normalize_agency_bank_account(bank_account_number)
    bank_name = _normalize_agency_bank_name(bank_name)
    ifsc_code = _normalize_agency_ifsc(ifsc_code)
    errors = []
    if not name:
        errors.append("Agency name is required.")
    else:
        existing = conn.execute(
            "SELECT id FROM agencies WHERE LOWER(name) = LOWER(?) LIMIT 1",
            (name,),
        ).fetchone()
        if existing and (agency_id is None or int(existing["id"]) != int(agency_id)):
            errors.append("An agency with this name already exists.")
    if gst and not is_valid_agency_gst(gst):
        errors.append("GST must be a valid 15-character GSTIN (e.g. 35AANFH8592H1ZS).")
    if ifsc_code and not is_valid_agency_ifsc(ifsc_code):
        errors.append("IFSC Code must be in format ABCD0123456 (4 letters, 0, 6 alphanumeric).")
    if errors:
        return None, errors

    if agency_id:
        try:
            agency_id = int(agency_id)
        except (TypeError, ValueError):
            return None, ["Agency not found."]
        cursor = conn.execute(
            f"""
            UPDATE agencies
            SET name = ?, phone = ?, gst = ?, address = ?,
                bank_account_number = ?, bank_name = ?, ifsc_code = ?,
                updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (name, phone, gst, address, bank_account_number, bank_name, ifsc_code, agency_id),
        )
        if cursor.rowcount <= 0:
            return None, ["Agency not found."]
        return agency_id, []

    cursor = conn.execute(
        f"""
        INSERT INTO agencies (
            name, phone, gst, address, bank_account_number, bank_name, ifsc_code,
            created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, {SQL_NOW}, {SQL_NOW})
        """,
        (name, phone, gst, address, bank_account_number, bank_name, ifsc_code),
    )
    return int(cursor.lastrowid), []


def upsert_agency_by_name(conn, name, gst="", address=""):
    """Create or update an agency matched by case-insensitive name.

    Invalid GST is ignored so address / name updates still persist.
    Blank GST or address leaves the existing master value in place.
    """
    ensure_agencies_schema(conn)
    name = _normalize_agency_name(name)
    if not name:
        return None
    gst = _normalize_agency_gst(gst)
    if gst and not is_valid_agency_gst(gst):
        gst = ""
    address = _normalize_agency_address(address)
    existing = conn.execute(
        "SELECT id, gst, address FROM agencies WHERE LOWER(name) = LOWER(?) LIMIT 1",
        (name,),
    ).fetchone()
    if existing:
        next_gst = gst or (existing["gst"] or "")
        next_address = address or (existing["address"] or "")
        conn.execute(
            f"""
            UPDATE agencies
            SET name = ?, gst = ?, address = ?, updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (name, next_gst, next_address, existing["id"]),
        )
        return get_agency(conn, existing["id"])
    saved_id, errors = save_agency_record(conn, name, gst, address)
    if errors:
        return None
    return get_agency(conn, saved_id)


def delete_agency_record(conn, agency_id):
    ensure_agencies_schema(conn)
    try:
        agency_id = int(agency_id)
    except (TypeError, ValueError):
        return False
    cursor = conn.execute("DELETE FROM agencies WHERE id = ?", (agency_id,))
    return cursor.rowcount > 0


def list_pos_menu_categories(
    conn, include_inactive=False, outlet=POS_OUTLET_RESTAURANT, outlets=None
):
    """Return menu categories with active item counts for one or more outlets."""
    ensure_pos_schema(conn)
    outlet_list = resolve_pos_outlets(outlet=outlet, outlets=outlets)
    placeholders = ", ".join("?" for _ in outlet_list)
    clauses = [f"c.outlet IN ({placeholders})"]
    params = list(outlet_list)
    if not include_inactive:
        clauses.append("c.is_active = 1")
    where = "WHERE " + " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            c.id,
            c.name,
            c.outlet,
            c.sort_order,
            c.is_visible,
            c.is_active,
            COALESCE(SUM(CASE WHEN i.is_active = 1 THEN 1 ELSE 0 END), 0) AS item_count
        FROM pos_menu_categories c
        LEFT JOIN pos_menu_items i ON i.category_id = c.id AND i.outlet = c.outlet
        {where}
        GROUP BY c.id
        ORDER BY c.outlet ASC, c.sort_order ASC, c.name COLLATE NOCASE ASC, c.id ASC
        """,
        params,
    ).fetchall()
    return [
        {
            "id": int(r["id"]),
            "name": r["name"] or "",
            "outlet": normalize_pos_outlet(r["outlet"]),
            "sort_order": int(r["sort_order"] or 0),
            "is_visible": bool(r["is_visible"]),
            "is_active": bool(r["is_active"]),
            "item_count": int(r["item_count"] or 0),
        }
        for r in rows
    ]


def save_pos_menu_category(conn, *, category_id=None, name="", is_visible=True, sort_order=None, outlet=POS_OUTLET_RESTAURANT):
    """Create or update a menu category. Returns the saved row dict."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name:
        raise ValueError("Category name is required.")
    if len(clean_name) > 80:
        raise ValueError("Category name must be 80 characters or fewer.")

    visible = 1 if is_visible else 0
    if category_id:
        existing = conn.execute(
            "SELECT id FROM pos_menu_categories WHERE id = ? AND is_active = 1 AND outlet = ?",
            (int(category_id), outlet),
        ).fetchone()
        if not existing:
            raise ValueError("Category not found.")
        dup = conn.execute(
            """
            SELECT id FROM pos_menu_categories
            WHERE is_active = 1 AND outlet = ? AND id != ? AND lower(name) = lower(?)
            """,
            (outlet, int(category_id), clean_name),
        ).fetchone()
        if dup:
            raise ValueError("A category with this name already exists.")
        if sort_order is None:
            conn.execute(
                f"""
                UPDATE pos_menu_categories
                SET name = ?, is_visible = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (clean_name, visible, int(category_id)),
            )
        else:
            conn.execute(
                f"""
                UPDATE pos_menu_categories
                SET name = ?, is_visible = ?, sort_order = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (clean_name, visible, int(sort_order), int(category_id)),
            )
        saved_id = int(category_id)
    else:
        dup = conn.execute(
            """
            SELECT id FROM pos_menu_categories
            WHERE is_active = 1 AND outlet = ? AND lower(name) = lower(?)
            """,
            (outlet, clean_name),
        ).fetchone()
        if dup:
            raise ValueError("A category with this name already exists.")
        if sort_order is None:
            max_row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS m FROM pos_menu_categories WHERE is_active = 1 AND outlet = ?",
                (outlet,),
            ).fetchone()
            sort_order = int(max_row["m"] or 0) + 10
        cur = conn.execute(
            f"""
            INSERT INTO pos_menu_categories (name, sort_order, is_visible, is_active, outlet, created_at, updated_at)
            VALUES (?, ?, ?, 1, ?, {SQL_NOW}, {SQL_NOW})
            """,
            (clean_name, int(sort_order), visible, outlet),
        )
        saved_id = int(cur.lastrowid)

    row = conn.execute(
        """
        SELECT
            c.id,
            c.name,
            c.sort_order,
            c.is_visible,
            c.is_active,
            COALESCE(SUM(CASE WHEN i.is_active = 1 THEN 1 ELSE 0 END), 0) AS item_count
        FROM pos_menu_categories c
        LEFT JOIN pos_menu_items i ON i.category_id = c.id
        WHERE c.id = ?
        GROUP BY c.id
        """,
        (saved_id,),
    ).fetchone()
    return {
        "id": int(row["id"]),
        "name": row["name"] or "",
        "sort_order": int(row["sort_order"] or 0),
        "is_visible": bool(row["is_visible"]),
        "is_active": bool(row["is_active"]),
        "item_count": int(row["item_count"] or 0),
    }


def soft_delete_pos_menu_category(conn, category_id):
    """Soft-delete a menu category (and its items)."""
    ensure_pos_schema(conn)
    existing = conn.execute(
        "SELECT id FROM pos_menu_categories WHERE id = ? AND is_active = 1",
        (int(category_id),),
    ).fetchone()
    if not existing:
        raise ValueError("Category not found.")
    conn.execute(
        f"""
        UPDATE pos_menu_items
        SET is_active = 0, updated_at = {SQL_NOW}
        WHERE category_id = ? AND is_active = 1
        """,
        (int(category_id),),
    )
    conn.execute(
        """
        DELETE FROM pos_menu_recipe_lines
        WHERE menu_item_id IN (
            SELECT id FROM pos_menu_items WHERE category_id = ?
        )
        """,
        (int(category_id),),
    )
    conn.execute(
        f"""
        UPDATE pos_menu_categories
        SET is_active = 0, updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (int(category_id),),
    )
    return True


# Margin % badge thresholds for Menu & Margin Calculator UI.
# ≥60% healthy (green), 30–60% moderate (orange), <30% low (red).
POS_MENU_MARGIN_HEALTHY_PCT = 60.0
POS_MENU_MARGIN_MODERATE_PCT = 30.0


def _normalize_pos_menu_unit(unit):
    """Normalize product/recipe unit aliases for cost conversion."""
    u = str(unit or "").strip().lower()
    if u in ("ltr", "l", "litre", "liters", "litres"):
        return "liter"
    if u in ("gram", "grams"):
        return "g"
    if u in ("kilogram", "kilograms", "kgs"):
        return "kg"
    if u in ("pc", "piece", "pieces"):
        return "pcs"
    return u or "pcs"


def _qty_in_product_units(qty, recipe_unit, product_unit):
    """Convert a recipe quantity into Product Master default-unit quantity.

    Returns None when units are incompatible (cannot cost the line).
    """
    try:
        amount = float(qty)
    except (TypeError, ValueError):
        return None
    if amount <= 0 or amount != amount:
        return None
    ru = _normalize_pos_menu_unit(recipe_unit)
    pu = _normalize_pos_menu_unit(product_unit)

    # Weight family
    if pu in ("kg", "g") and ru in ("kg", "g"):
        grams = amount * 1000.0 if ru == "kg" else amount
        return grams / 1000.0 if pu == "kg" else grams
    # Volume family
    if pu in ("liter", "ml") and ru in ("liter", "ml"):
        ml = amount * 1000.0 if ru == "liter" else amount
        return ml / 1000.0 if pu == "liter" else ml
    # Count family
    if pu in ("pcs", "dozen") and ru in ("pcs", "dozen"):
        pieces = amount * 12.0 if ru == "dozen" else amount
        return pieces / 12.0 if pu == "dozen" else pieces
    # Same unit (bunch, bottle, pack, case, …)
    if pu == ru:
        return amount
    return None


def recipe_line_food_cost(qty, recipe_unit, product_unit, unit_price):
    """Cost of one recipe line: qty × unit price after unit conversion.

    ``unit_price`` is Product Master approximate_price per default unit.
    Returns None when price or units are missing/incompatible.
    """
    try:
        price = float(unit_price) if unit_price is not None else None
    except (TypeError, ValueError):
        price = None
    if price is None or price < 0 or price != price:
        return None
    converted = _qty_in_product_units(qty, recipe_unit, product_unit)
    if converted is None:
        return None
    return round(converted * price, 4)


def margin_band_for_pct(margin_pct):
    """Return 'healthy' | 'moderate' | 'low' | None for a margin percentage."""
    if margin_pct is None:
        return None
    try:
        pct = float(margin_pct)
    except (TypeError, ValueError):
        return None
    if pct != pct:  # NaN
        return None
    if pct >= POS_MENU_MARGIN_HEALTHY_PCT:
        return "healthy"
    if pct >= POS_MENU_MARGIN_MODERATE_PCT:
        return "moderate"
    return "low"


def margin_status_for_pct(margin_pct):
    """Return Excellent/Good/Average/Low/Critical label for margin analysis UI."""
    if margin_pct is None:
        return None
    try:
        pct = float(margin_pct)
    except (TypeError, ValueError):
        return None
    if pct != pct:
        return None
    if pct >= 70.0:
        return "excellent"
    if pct >= POS_MENU_MARGIN_HEALTHY_PCT:
        return "good"
    if pct >= 45.0:
        return "average"
    if pct >= POS_MENU_MARGIN_MODERATE_PCT:
        return "low"
    return "critical"


def recommended_selling_price(food_cost, target_margin_pct):
    """Selling price needed to hit target margin % given food cost."""
    try:
        cost = float(food_cost)
        target = float(target_margin_pct)
    except (TypeError, ValueError):
        return None
    if cost < 0 or cost != cost or target != target:
        return None
    if target >= 100.0 or target < 0:
        return None
    denom = 1.0 - (target / 100.0)
    if denom <= 0:
        return None
    return round(cost / denom, 2)


def compute_pos_menu_item_margins(selling_price, food_cost):
    """Derive gross margin ₹ / % and badge band from selling price + food cost.

    Missing food cost → food_cost 0 treated as unknown (None metrics) when
    recipe has no priced ingredients; callers pass food_cost=None for that case.
    """
    try:
        price = float(selling_price or 0)
    except (TypeError, ValueError):
        price = 0.0
    if food_cost is None:
        return {
            "food_cost": None,
            "gross_margin": None,
            "margin_pct": None,
            "food_cost_pct": None,
            "margin_band": None,
            "margin_status": None,
        }
    try:
        cost = float(food_cost)
    except (TypeError, ValueError):
        cost = 0.0
    if cost < 0 or cost != cost:
        cost = 0.0
    cost = round(cost, 2)
    if price <= 0:
        return {
            "food_cost": cost,
            "gross_margin": None,
            "margin_pct": None,
            "food_cost_pct": None,
            "margin_band": None,
            "margin_status": None,
        }
    gross = round(price - cost, 2)
    margin_pct = round((gross / price) * 100.0, 2)
    food_cost_pct = round((cost / price) * 100.0, 2)
    return {
        "food_cost": cost,
        "gross_margin": gross,
        "margin_pct": margin_pct,
        "food_cost_pct": food_cost_pct,
        "margin_band": margin_band_for_pct(margin_pct),
        "margin_status": margin_status_for_pct(margin_pct),
    }


def _pos_menu_recipe_line_dict(row):
    """Normalize a recipe join row."""
    price = row["approximate_price"] if "approximate_price" in row.keys() else None
    try:
        price_val = float(price) if price is not None else None
    except (TypeError, ValueError):
        price_val = None
    qty = float(row["qty"] or 0)
    unit = (row["unit"] or "g").strip() or "g"
    product_unit = (row["product_unit"] if "product_unit" in row.keys() else None) or ""
    product_outlet = ""
    if "product_outlet" in row.keys() and row["product_outlet"] is not None:
        product_outlet = str(row["product_outlet"] or "").strip().lower()
    line_cost = recipe_line_food_cost(qty, unit, product_unit, price_val)
    return {
        "id": int(row["id"]),
        "menu_item_id": int(row["menu_item_id"]),
        "product_id": int(row["product_id"]),
        "product_name": (row["product_name"] if "product_name" in row.keys() else None) or "",
        "product_unit": product_unit,
        "product_outlet": product_outlet or "restaurant",
        "approximate_price": price_val,
        "qty": qty,
        "unit": unit,
        "sort_order": int(row["sort_order"] or 0),
        "line_cost": line_cost,
    }


def list_pos_menu_recipe_lines(conn, menu_item_ids=None):
    """Return recipe lines for one or many menu items (keyed later by caller)."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    if menu_item_ids is None:
        return []
    if isinstance(menu_item_ids, (int, str)):
        ids = [int(menu_item_ids)]
    else:
        ids = [int(x) for x in menu_item_ids if x is not None]
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"""
        SELECT
            r.id,
            r.menu_item_id,
            r.product_id,
            r.qty,
            r.unit,
            r.sort_order,
            p.name AS product_name,
            p.default_unit AS product_unit,
            p.outlet AS product_outlet,
            p.approximate_price AS approximate_price
        FROM pos_menu_recipe_lines r
        LEFT JOIN store_products p ON p.id = r.product_id
        WHERE r.menu_item_id IN ({placeholders})
        ORDER BY r.menu_item_id ASC, r.sort_order ASC, r.id ASC
        """,
        ids,
    ).fetchall()
    return [_pos_menu_recipe_line_dict(r) for r in rows]


def _attach_pos_menu_recipes(conn, items, include_recipe_lines=True):
    """Attach margin fields onto each menu item; optionally keep full recipe[].

    List views need food_cost / margin columns but not every ingredient line in JSON.
    Detail / edit still pass include_recipe_lines=True.
    """
    if not items:
        return items
    by_id = {int(it["id"]): it for it in items}
    for it in items:
        it["recipe"] = []
    lines = list_pos_menu_recipe_lines(conn, list(by_id.keys()))
    for line in lines:
        mid = int(line["menu_item_id"])
        if mid in by_id:
            by_id[mid]["recipe"].append(line)
    for it in items:
        recipe = it.get("recipe") or []
        if not recipe:
            margins = compute_pos_menu_item_margins(it.get("rate"), None)
        else:
            costs = [line.get("line_cost") for line in recipe]
            if any(c is None for c in costs):
                # Partial pricing: sum known lines; still show a cost when any priced.
                known = [c for c in costs if c is not None]
                food_cost = round(sum(known), 2) if known else None
            else:
                food_cost = round(sum(costs), 2)
            margins = compute_pos_menu_item_margins(it.get("rate"), food_cost)
        it.update(margins)
        if not include_recipe_lines:
            it["recipe"] = []
    return items


def _default_recipe_unit(product_unit):
    """Weight/volume products default recipe qty to grams."""
    unit = (product_unit or "").strip().lower()
    if unit in ("kg", "liter", "ltr", "l", "litre"):
        return "g"
    return (product_unit or "g").strip() or "g"


def replace_pos_menu_recipe_lines(conn, menu_item_id, recipe):
    """Replace all recipe lines for a menu item. Returns the saved lines."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    mid = int(menu_item_id)
    existing = conn.execute(
        "SELECT id FROM pos_menu_items WHERE id = ?",
        (mid,),
    ).fetchone()
    if not existing:
        raise ValueError("Menu item not found.")

    conn.execute("DELETE FROM pos_menu_recipe_lines WHERE menu_item_id = ?", (mid,))

    if not recipe:
        return []
    if not isinstance(recipe, list):
        raise ValueError("Recipe must be a list of ingredients.")

    seen = set()
    sort_i = 0
    for raw in recipe:
        if not isinstance(raw, dict):
            continue
        try:
            product_id = int(raw.get("product_id"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid recipe product.") from exc
        if product_id in seen:
            raise ValueError("Each product can only appear once in the recipe.")
        product_row = conn.execute(
            """
            SELECT id, name, default_unit
            FROM store_products
            WHERE id = ? AND is_active = 1
            """,
            (product_id,),
        ).fetchone()
        if not product_row:
            raise ValueError("Recipe product not found in Product Master.")

        try:
            qty = float(raw.get("qty"))
        except (TypeError, ValueError) as exc:
            raise ValueError("Recipe quantity must be a number.") from exc
        if qty <= 0:
            raise ValueError("Recipe quantity must be greater than zero.")

        unit = " ".join(str(raw.get("unit") or "").split()).strip()
        if not unit:
            unit = _default_recipe_unit(product_row["default_unit"])
        if len(unit) > 40:
            raise ValueError("Recipe unit is too long.")

        conn.execute(
            """
            INSERT INTO pos_menu_recipe_lines (menu_item_id, product_id, qty, unit, sort_order)
            VALUES (?, ?, ?, ?, ?)
            """,
            (mid, product_id, qty, unit, sort_i),
        )
        seen.add(product_id)
        sort_i += 1

    return list_pos_menu_recipe_lines(conn, mid)


def _pos_menu_item_dict(row):
    """Normalize a pos_menu_items join row to a JSON-friendly dict."""
    product_id = row["product_id"]
    rate = row["rate"]
    category_visible = True
    if "category_visible" in row.keys() and row["category_visible"] is not None:
        category_visible = bool(row["category_visible"])
    keys = row.keys()

    def _text(col, default=""):
        if col not in keys or row[col] is None:
            return default
        return str(row[col] or default)

    prep_time = None
    if "prep_time_mins" in keys and row["prep_time_mins"] is not None:
        try:
            prep_time = int(row["prep_time_mins"])
        except (TypeError, ValueError):
            prep_time = None

    target_margin = None
    if "target_margin_pct" in keys and row["target_margin_pct"] is not None:
        try:
            target_margin = float(row["target_margin_pct"])
        except (TypeError, ValueError):
            target_margin = None

    portion = _text("portion_size")
    if not portion:
        portion = _text("variant")

    return {
        "id": int(row["id"]),
        "category_id": int(row["category_id"]),
        "category_name": (row["category_name"] if "category_name" in keys else None) or "",
        "category_visible": category_visible,
        "product_id": int(product_id) if product_id not in (None, "") else None,
        "product_name": (row["product_name"] if "product_name" in keys else None) or "",
        "product_unit": (row["product_unit"] if "product_unit" in keys else None) or "",
        "name": row["name"] or "",
        "code": row["code"] or "",
        "barcode": row["barcode"] or "",
        "variant": row["variant"] or "",
        "menu_type": _text("menu_type"),
        "item_kind": (
            "liquor"
            if str(_text("item_kind") or "food").strip().lower()
            in ("liquor", "liquour", "alcohol", "bar")
            else "food"
        ),
        "portion_size": portion,
        "prep_time_mins": prep_time,
        "shelf_life": _text("shelf_life"),
        "notes": _text("notes"),
        "target_margin_pct": target_margin if target_margin is not None else POS_MENU_MARGIN_HEALTHY_PCT,
        "updated_by": _text("updated_by"),
        "created_at": _text("created_at") if "created_at" in keys else "",
        "updated_at": _text("updated_at") if "updated_at" in keys else "",
        "rate": float(rate or 0),
        "sort_order": int(row["sort_order"] or 0),
        "is_active": bool(row["is_active"]),
        "outlet": normalize_pos_outlet(row["outlet"] if "outlet" in keys else None),
        "status": "visible" if category_visible else "hidden",
        "recipe": [],
        "food_cost": None,
        "gross_margin": None,
        "margin_pct": None,
        "food_cost_pct": None,
        "margin_band": None,
        "margin_status": None,
    }


_POS_MENU_ITEM_SELECT = """
            i.id,
            i.category_id,
            i.product_id,
            i.name,
            i.code,
            i.barcode,
            i.variant,
            i.rate,
            i.sort_order,
            i.is_active,
            i.outlet,
            i.menu_type,
            i.item_kind,
            i.portion_size,
            i.prep_time_mins,
            i.shelf_life,
            i.notes,
            i.target_margin_pct,
            i.updated_by,
            i.created_at,
            i.updated_at,
            c.name AS category_name,
            c.is_visible AS category_visible,
            p.name AS product_name,
            p.default_unit AS product_unit
"""


def list_pos_menu_items(
    conn,
    category_id=None,
    include_inactive=False,
    outlet=POS_OUTLET_RESTAURANT,
    outlets=None,
    include_recipe_lines=False,
):
    """Return menu items, optionally filtered by category and one or more outlets.

    By default omits recipe ingredient arrays from the payload (margins still computed)
    so catalog list responses stay small for soft-nav / large menus.
    """
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    outlet_list = resolve_pos_outlets(outlet=outlet, outlets=outlets)
    placeholders = ", ".join("?" for _ in outlet_list)
    clauses = [f"i.outlet IN ({placeholders})"]
    params = list(outlet_list)
    if not include_inactive:
        clauses.append("i.is_active = 1")
    if category_id is not None:
        clauses.append("i.category_id = ?")
        params.append(int(category_id))
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"""
        SELECT
            {_POS_MENU_ITEM_SELECT}
        FROM pos_menu_items i
        LEFT JOIN pos_menu_categories c ON c.id = i.category_id
        LEFT JOIN store_products p ON p.id = i.product_id
        {where}
        ORDER BY i.outlet ASC, i.sort_order ASC, i.name COLLATE NOCASE ASC, i.id ASC
        """,
        params,
    ).fetchall()
    items = [_pos_menu_item_dict(r) for r in rows]
    return _attach_pos_menu_recipes(conn, items, include_recipe_lines=include_recipe_lines)


def get_pos_menu_item(conn, item_id):
    """Return one active menu item with recipe + margin fields, or None."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    row = conn.execute(
        f"""
        SELECT
            {_POS_MENU_ITEM_SELECT}
        FROM pos_menu_items i
        LEFT JOIN pos_menu_categories c ON c.id = i.category_id
        LEFT JOIN store_products p ON p.id = i.product_id
        WHERE i.id = ? AND i.is_active = 1
        """,
        (int(item_id),),
    ).fetchone()
    if not row:
        return None
    return _attach_pos_menu_recipes(conn, [_pos_menu_item_dict(row)])[0]


def save_pos_menu_item(
    conn,
    *,
    item_id=None,
    category_id=None,
    product_id=None,
    name="",
    code="",
    barcode="",
    variant="",
    rate=0,
    sort_order=None,
    recipe=None,
    menu_type=None,
    item_kind=None,
    portion_size=None,
    prep_time_mins=None,
    shelf_life=None,
    notes=None,
    target_margin_pct=None,
    updated_by=None,
    price_change_reason="",
    outlet=POS_OUTLET_RESTAURANT,
):
    """Create or update a menu item; optional recipe[] replaces ingredient lines."""
    ensure_pos_schema(conn)
    ensure_stores_schema(conn)
    outlet = normalize_pos_outlet(outlet)

    try:
        cat_id = int(category_id) if category_id not in (None, "") else None
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid category.") from exc
    if not cat_id:
        raise ValueError("Category is required.")
    cat = conn.execute(
        "SELECT id FROM pos_menu_categories WHERE id = ? AND is_active = 1 AND outlet = ?",
        (cat_id, outlet),
    ).fetchone()
    if not cat:
        raise ValueError("Category not found.")

    prod_id = None
    product_row = None
    if product_id not in (None, ""):
        try:
            prod_id = int(product_id)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid product.") from exc
        product_row = conn.execute(
            """
            SELECT id, name, default_unit, approximate_price, outlet
            FROM store_products
            WHERE id = ? AND is_active = 1
            """,
            (prod_id,),
        ).fetchone()
        if not product_row:
            raise ValueError("Product not found in Product Master.")

    clean_name = " ".join(str(name or "").split()).strip()
    if not clean_name and product_row:
        clean_name = (product_row["name"] or "").strip()
    if not clean_name:
        raise ValueError("Item name is required.")
    if len(clean_name) > 120:
        raise ValueError("Item name must be 120 characters or fewer.")

    clean_code = " ".join(str(code or "").split()).strip()[:40]
    clean_barcode = " ".join(str(barcode or "").split()).strip()[:64]
    clean_variant = " ".join(str(variant or "").split()).strip()[:80]

    try:
        rate_val = float(rate if rate not in (None, "") else 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("Rate must be a number.") from exc
    if rate_val < 0:
        raise ValueError("Rate cannot be negative.")
    if rate_val == 0 and product_row and product_row["approximate_price"] is not None:
        try:
            approx = float(product_row["approximate_price"])
            if approx > 0:
                rate_val = approx
        except (TypeError, ValueError):
            pass

    existing_row = None
    if item_id:
        existing_row = conn.execute(
            """
            SELECT id, rate, menu_type, item_kind, portion_size, prep_time_mins, shelf_life,
                   notes, target_margin_pct, updated_by, variant
            FROM pos_menu_items
            WHERE id = ? AND is_active = 1
            """,
            (int(item_id),),
        ).fetchone()
        if not existing_row:
            raise ValueError("Menu item not found.")

    if existing_row:
        cur_menu_type = (existing_row["menu_type"] or "") if "menu_type" in existing_row.keys() else ""
        cur_item_kind = (
            (existing_row["item_kind"] or "food") if "item_kind" in existing_row.keys() else "food"
        )
        cur_portion = (existing_row["portion_size"] or "") if "portion_size" in existing_row.keys() else ""
        cur_prep = existing_row["prep_time_mins"] if "prep_time_mins" in existing_row.keys() else None
        cur_shelf = (existing_row["shelf_life"] or "") if "shelf_life" in existing_row.keys() else ""
        cur_notes = (existing_row["notes"] or "") if "notes" in existing_row.keys() else ""
        cur_target = (
            existing_row["target_margin_pct"] if "target_margin_pct" in existing_row.keys() else None
        )
        cur_updated_by = (existing_row["updated_by"] or "") if "updated_by" in existing_row.keys() else ""
    else:
        cur_menu_type = ""
        cur_item_kind = "food"
        cur_portion = ""
        cur_prep = None
        cur_shelf = ""
        cur_notes = ""
        cur_target = POS_MENU_MARGIN_HEALTHY_PCT
        cur_updated_by = ""

    if menu_type is None:
        clean_menu_type = cur_menu_type
    else:
        clean_menu_type = str(menu_type or "").strip().lower()
    if clean_menu_type in ("non-veg", "nonveg", "non veg"):
        clean_menu_type = "non_veg"
    if clean_menu_type in ("liquour", "alcohol"):
        clean_menu_type = "liquor"
    if clean_menu_type not in ("", "veg", "non_veg", "liquor"):
        raise ValueError("Menu type must be Veg, Non-Veg, or Liquor.")
    clean_menu_type = clean_menu_type[:20]

    if item_kind is None:
        # Liquor menu type implies liquor tax class when kind wasn't sent.
        if clean_menu_type == "liquor":
            clean_item_kind = "liquor"
        else:
            clean_item_kind = str(cur_item_kind or "food").strip().lower()
    else:
        clean_item_kind = str(item_kind or "food").strip().lower()
    if clean_menu_type == "liquor":
        clean_item_kind = "liquor"
    if clean_item_kind in ("liquour", "alcohol", "bar"):
        clean_item_kind = "liquor"
    if clean_item_kind not in ("food", "liquor"):
        raise ValueError("Item type must be Food or Liquor.")

    if portion_size is not None:
        clean_portion = " ".join(str(portion_size or "").split()).strip()[:80]
    elif not existing_row and clean_variant:
        clean_portion = clean_variant
    else:
        clean_portion = cur_portion or ""
    if (
        portion_size is not None
        and clean_portion
        and (not existing_row or not (existing_row["variant"] or "").strip())
        and not clean_variant
    ):
        clean_variant = clean_portion

    if prep_time_mins is None:
        clean_prep = cur_prep
    elif prep_time_mins in ("",):
        clean_prep = None
    else:
        try:
            clean_prep = int(prep_time_mins)
        except (TypeError, ValueError) as exc:
            raise ValueError("Prep time must be a whole number of minutes.") from exc
        if clean_prep < 0:
            raise ValueError("Prep time cannot be negative.")

    clean_shelf = (
        " ".join(str(shelf_life or "").split()).strip()[:80]
        if shelf_life is not None
        else cur_shelf
    )
    clean_notes = str(notes) if notes is not None else cur_notes
    if clean_notes is None:
        clean_notes = ""
    if len(clean_notes) > 8000:
        raise ValueError("Notes are too long.")

    if target_margin_pct is None:
        clean_target = cur_target if cur_target is not None else POS_MENU_MARGIN_HEALTHY_PCT
    elif target_margin_pct in ("",):
        clean_target = POS_MENU_MARGIN_HEALTHY_PCT
    else:
        try:
            clean_target = float(target_margin_pct)
        except (TypeError, ValueError) as exc:
            raise ValueError("Target margin must be a number.") from exc
        if clean_target < 0 or clean_target >= 100:
            raise ValueError("Target margin must be between 0 and 100.")

    clean_updated_by = (
        " ".join(str(updated_by or "").split()).strip()[:120]
        if updated_by is not None
        else cur_updated_by
    )

    if item_id:
        old_rate = float(existing_row["rate"] or 0)
        if sort_order is None:
            conn.execute(
                f"""
                UPDATE pos_menu_items
                SET category_id = ?, product_id = ?, name = ?, code = ?, barcode = ?,
                    variant = ?, rate = ?, menu_type = ?, item_kind = ?, portion_size = ?,
                    prep_time_mins = ?, shelf_life = ?, notes = ?,
                    target_margin_pct = ?, updated_by = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (
                    cat_id,
                    prod_id,
                    clean_name,
                    clean_code,
                    clean_barcode,
                    clean_variant,
                    rate_val,
                    clean_menu_type,
                    clean_item_kind,
                    clean_portion,
                    clean_prep,
                    clean_shelf,
                    clean_notes,
                    clean_target,
                    clean_updated_by,
                    int(item_id),
                ),
            )
        else:
            conn.execute(
                f"""
                UPDATE pos_menu_items
                SET category_id = ?, product_id = ?, name = ?, code = ?, barcode = ?,
                    variant = ?, rate = ?, sort_order = ?, menu_type = ?, item_kind = ?,
                    portion_size = ?,
                    prep_time_mins = ?, shelf_life = ?, notes = ?,
                    target_margin_pct = ?, updated_by = ?, updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (
                    cat_id,
                    prod_id,
                    clean_name,
                    clean_code,
                    clean_barcode,
                    clean_variant,
                    rate_val,
                    int(sort_order),
                    clean_menu_type,
                    clean_item_kind,
                    clean_portion,
                    clean_prep,
                    clean_shelf,
                    clean_notes,
                    clean_target,
                    clean_updated_by,
                    int(item_id),
                ),
            )
        saved_id = int(item_id)
        if abs(old_rate - rate_val) > 0.0001:
            record_pos_menu_price_change(
                conn,
                saved_id,
                old_price=old_rate,
                new_price=rate_val,
                reason=price_change_reason or "Rate updated",
                updated_by=clean_updated_by,
            )
    else:
        if sort_order is None:
            max_row = conn.execute(
                """
                SELECT COALESCE(MAX(sort_order), 0) AS m
                FROM pos_menu_items
                WHERE category_id = ? AND is_active = 1
                """,
                (cat_id,),
            ).fetchone()
            sort_order = int(max_row["m"] or 0) + 10
        cur = conn.execute(
            f"""
            INSERT INTO pos_menu_items (
                category_id, product_id, name, code, barcode, variant, rate,
                sort_order, is_active, menu_type, item_kind, portion_size, prep_time_mins,
                shelf_life, notes, target_margin_pct, updated_by, outlet,
                created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, {SQL_NOW}, {SQL_NOW})
            """,
            (
                cat_id,
                prod_id,
                clean_name,
                clean_code,
                clean_barcode,
                clean_variant,
                rate_val,
                int(sort_order),
                clean_menu_type,
                clean_item_kind,
                clean_portion,
                clean_prep,
                clean_shelf,
                clean_notes,
                clean_target,
                clean_updated_by,
                outlet,
            ),
        )
        saved_id = int(cur.lastrowid)

    if recipe is not None:
        replace_pos_menu_recipe_lines(conn, saved_id, recipe)
    elif not item_id:
        replace_pos_menu_recipe_lines(conn, saved_id, [])

    item = get_pos_menu_item(conn, saved_id)
    if not item:
        raise ValueError("Menu item not found after save.")
    return item


def record_pos_menu_price_change(
    conn, menu_item_id, *, old_price, new_price, reason="", updated_by=""
):
    """Append a selling-price history row."""
    ensure_pos_schema(conn)
    try:
        old_v = float(old_price)
        new_v = float(new_price)
    except (TypeError, ValueError):
        return None
    conn.execute(
        f"""
        INSERT INTO pos_menu_price_history (
            menu_item_id, old_price, new_price, reason, updated_by, created_at
        )
        VALUES (?, ?, ?, ?, ?, {SQL_NOW})
        """,
        (
            int(menu_item_id),
            round(old_v, 2),
            round(new_v, 2),
            " ".join(str(reason or "").split()).strip()[:200],
            " ".join(str(updated_by or "").split()).strip()[:120],
        ),
    )
    return True


def list_pos_menu_price_history(conn, menu_item_id, limit=50):
    """Return newest-first price history for a menu item."""
    ensure_pos_schema(conn)
    try:
        lim = max(1, min(int(limit or 50), 200))
    except (TypeError, ValueError):
        lim = 50
    rows = conn.execute(
        """
        SELECT id, menu_item_id, old_price, new_price, reason, updated_by, created_at
        FROM pos_menu_price_history
        WHERE menu_item_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT ?
        """,
        (int(menu_item_id), lim),
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "id": int(r["id"]),
                "menu_item_id": int(r["menu_item_id"]),
                "old_price": float(r["old_price"] or 0),
                "new_price": float(r["new_price"] or 0),
                "reason": r["reason"] or "",
                "updated_by": r["updated_by"] or "",
                "created_at": r["created_at"] or "",
            }
        )
    return out


def _fifo_remaining_layers(conn, item_name, unit):
    """Rebuild remaining receive layers for a stock item using FIFO drain.

    Returns list of dicts: batch_no, purchase_date, supplier, available_qty,
    unit_cost, unit, movement_id.
    """
    ensure_stores_schema(conn)
    name = " ".join(str(item_name or "").split()).strip()
    unit_key = " ".join(str(unit or "").split()).strip()
    if not name:
        return []
    rows = conn.execute(
        """
        SELECT id, qty_delta, movement_type, unit_cost, notes, created_at, unit
        FROM store_stock_movements
        WHERE lower(item_name) = lower(?)
          AND lower(unit) = lower(?)
        ORDER BY created_at ASC, id ASC
        """,
        (name, unit_key),
    ).fetchall()
    layers = []
    for row in rows:
        try:
            qty = float(row["qty_delta"] or 0)
        except (TypeError, ValueError):
            continue
        mtype = (row["movement_type"] or "").strip().lower()
        if mtype == "receive" and qty > 0:
            try:
                unit_cost = float(row["unit_cost"]) if row["unit_cost"] is not None else None
            except (TypeError, ValueError):
                unit_cost = None
            supplier = ""
            notes = (row["notes"] or "").strip()
            if notes.lower().startswith("received from "):
                supplier = notes[14:].strip()
            elif notes:
                supplier = notes[:80]
            layers.append(
                {
                    "movement_id": int(row["id"]),
                    "purchase_date": (row["created_at"] or "")[:10],
                    "supplier": supplier or "—",
                    "available_qty": qty,
                    "unit_cost": unit_cost,
                    "unit": row["unit"] or unit_key,
                }
            )
            continue
        drain = abs(qty) if qty < 0 else (
            qty if mtype in ("issue", "adjust", "waste", "transfer", "sale", "consume") else 0
        )
        if drain <= 0:
            continue
        remaining = drain
        for layer in layers:
            if remaining <= 0:
                break
            take = min(layer["available_qty"], remaining)
            layer["available_qty"] = round(layer["available_qty"] - take, 4)
            remaining = round(remaining - take, 4)
        layers = [layer for layer in layers if layer["available_qty"] > 0.0001]
    out = []
    for idx, layer in enumerate(layers, start=1):
        out.append(
            {
                "batch_no": f"B-{layer['movement_id']}",
                "batch_index": idx,
                "purchase_date": layer["purchase_date"],
                "supplier": layer["supplier"],
                "available_qty": round(layer["available_qty"], 4),
                "unit_cost": layer["unit_cost"],
                "unit": layer["unit"],
                "movement_id": layer["movement_id"],
            }
        )
    return out


def allocate_fifo_for_qty(layers, qty_needed):
    """Allocate qty_needed across FIFO layers. Returns (rows, total_cost, fully_covered)."""
    try:
        need = float(qty_needed)
    except (TypeError, ValueError):
        return [], None, False
    if need <= 0:
        return [], 0.0, True
    rows = []
    remaining = need
    total_cost = 0.0
    priced_ok = True
    for layer in layers:
        if remaining <= 0:
            break
        avail = float(layer.get("available_qty") or 0)
        if avail <= 0:
            continue
        take = min(avail, remaining)
        unit_cost = layer.get("unit_cost")
        cost_used = None
        if unit_cost is not None:
            try:
                cost_used = round(take * float(unit_cost), 4)
                total_cost += cost_used
            except (TypeError, ValueError):
                priced_ok = False
                cost_used = None
        else:
            priced_ok = False
        rows.append(
            {
                "batch_no": layer.get("batch_no") or "",
                "purchase_date": layer.get("purchase_date") or "",
                "supplier": layer.get("supplier") or "—",
                "available_qty": round(avail, 4),
                "unit_cost": unit_cost,
                "qty_used": round(take, 4),
                "cost_used": cost_used,
                "unit": layer.get("unit") or "",
                "product_name": layer.get("product_name") or "",
            }
        )
        remaining = round(remaining - take, 4)
    fully = remaining <= 0.0001
    if not rows:
        return [], None, False
    if not priced_ok:
        return rows, None, fully
    return rows, round(total_cost, 4), fully


def build_pos_menu_fifo_costing(conn, recipe_lines):
    """FIFO batch usage for a recipe. Falls back when stock batches are missing.

    Returns dict with batches, fifo_food_cost, fifo_available, note.
    """
    ensure_stores_schema(conn)
    batches = []
    line_costs = []
    any_layers = False
    all_covered = True
    if not recipe_lines:
        return {
            "batches": [],
            "fifo_food_cost": None,
            "fifo_available": False,
            "fifo_partial": False,
            "note": "No recipe ingredients to cost.",
        }

    for line in recipe_lines:
        product_name = (line.get("product_name") or "").strip()
        product_unit = (line.get("product_unit") or "").strip() or "pcs"
        qty = line.get("qty")
        recipe_unit = line.get("unit") or "g"
        converted = _qty_in_product_units(qty, recipe_unit, product_unit)
        layers = _fifo_remaining_layers(conn, product_name, product_unit) if product_name else []
        for layer in layers:
            layer["product_name"] = product_name
        if layers:
            any_layers = True
        if converted is None:
            all_covered = False
            continue
        rows, cost, fully = allocate_fifo_for_qty(layers, converted)
        for row in rows:
            row["ingredient"] = product_name
            row["required_qty"] = float(qty or 0)
            row["required_unit"] = recipe_unit
            batches.append(row)
        if cost is None or not fully:
            all_covered = False
        elif cost is not None:
            line_costs.append(cost)

    if not any_layers:
        return {
            "batches": [],
            "fifo_food_cost": None,
            "fifo_available": False,
            "fifo_partial": False,
            "note": (
                "FIFO batches unavailable — no stock receive movements found for these "
                "ingredients. Showing approximate Product Master food cost instead."
            ),
        }

    fifo_available = bool(line_costs and all_covered)
    fifo_food_cost = round(sum(line_costs), 2) if line_costs else None
    if fifo_available:
        note = "Food cost allocated from oldest stock receive batches (FIFO)."
    else:
        note = (
            "Partial FIFO coverage — some ingredients lack priced batches or stock. "
            "Use approximate food cost where FIFO is incomplete."
        )
    return {
        "batches": batches,
        "fifo_food_cost": fifo_food_cost,
        "fifo_available": fifo_available,
        "fifo_partial": bool(any_layers and not all_covered and line_costs),
        "note": note,
    }


def get_pos_menu_item_details(conn, item_id):
    """Rich payload for Menu Details popup (recipe, FIFO, history, analysis)."""
    item = get_pos_menu_item(conn, item_id)
    if not item:
        return None

    recipe = item.get("recipe") or []
    fifo = build_pos_menu_fifo_costing(conn, recipe)
    approx_food_cost = item.get("food_cost")
    fifo_cost = fifo.get("fifo_food_cost")
    display_food_cost = (
        fifo_cost if fifo.get("fifo_available") and fifo_cost is not None else approx_food_cost
    )
    margins = compute_pos_menu_item_margins(item.get("rate"), display_food_cost)
    target = item.get("target_margin_pct")
    if target is None:
        target = POS_MENU_MARGIN_HEALTHY_PCT
    recommended = recommended_selling_price(display_food_cost, target)

    analysis = {
        "selling_price": float(item.get("rate") or 0),
        "fifo_food_cost": display_food_cost,
        "approximate_food_cost": approx_food_cost,
        "gross_profit": margins.get("gross_margin"),
        "margin_pct": margins.get("margin_pct"),
        "food_cost_pct": margins.get("food_cost_pct"),
        "target_margin_pct": target,
        "recommended_selling_price": recommended,
        "profit_per_portion": margins.get("gross_margin"),
        "margin_status": margins.get("margin_status"),
        "margin_band": margins.get("margin_band"),
        "cost_source": "fifo" if fifo.get("fifo_available") else "approximate",
    }

    detail = dict(item)
    detail.update(margins)
    detail["food_cost"] = approx_food_cost
    detail["display_food_cost"] = display_food_cost
    detail["fifo"] = fifo
    detail["analysis"] = analysis
    detail["price_history"] = list_pos_menu_price_history(conn, item_id)
    detail["recipe_total_cost"] = approx_food_cost
    detail["inventory_url"] = "/stores/stock?outlet=restaurant"
    return detail


def soft_delete_pos_menu_item(conn, item_id):
    """Soft-delete a menu item and clear its recipe lines."""
    ensure_pos_schema(conn)
    existing = conn.execute(
        "SELECT id FROM pos_menu_items WHERE id = ? AND is_active = 1",
        (int(item_id),),
    ).fetchone()
    if not existing:
        raise ValueError("Menu item not found.")
    conn.execute("DELETE FROM pos_menu_recipe_lines WHERE menu_item_id = ?", (int(item_id),))
    conn.execute(
        f"""
        UPDATE pos_menu_items
        SET is_active = 0, updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (int(item_id),),
    )
    return True


def list_store_products_lite(conn, *, outlets=None, q=""):
    """Active Product Master rows for pickers (id, name, unit, outlet, price)."""
    ensure_stores_schema(conn)
    clauses = ["p.is_active = 1"]
    params = []
    if outlets:
        keys = [str(o or "").strip().lower() for o in outlets if str(o or "").strip()]
        if keys:
            placeholders = ",".join("?" for _ in keys)
            clauses.append(f"lower(p.outlet) IN ({placeholders})")
            params.extend(keys)
    needle = " ".join(str(q or "").split()).strip().lower()
    if needle:
        clauses.append("lower(p.name) LIKE ?")
        params.append(f"%{needle}%")
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            p.id,
            p.name,
            p.default_unit,
            p.outlet,
            p.approximate_price,
            c.name AS category_name
        FROM store_products p
        LEFT JOIN store_product_categories c
          ON c.id = p.category_id AND c.is_active = 1
        WHERE {where}
        ORDER BY
            CASE lower(p.outlet)
                WHEN 'restaurant' THEN 0
                WHEN 'both' THEN 1
                ELSE 2
            END,
            p.name COLLATE NOCASE ASC,
            p.id ASC
        LIMIT 500
        """,
        params,
    ).fetchall()
    result = []
    for r in rows:
        price = r["approximate_price"]
        try:
            price_val = float(price) if price is not None else None
        except (TypeError, ValueError):
            price_val = None
        result.append(
            {
                "id": int(r["id"]),
                "name": r["name"] or "",
                "default_unit": r["default_unit"] or "",
                "outlet": (r["outlet"] or "").strip().lower() or "restaurant",
                "approximate_price": price_val,
                "category_name": r["category_name"] or "",
            }
        )
    return result


def get_pos_floor_layout(conn, outlet=POS_OUTLET_RESTAURANT):
    """Load floor areas/tables JSON for an outlet; returns empty lists when unset."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    row = conn.execute(
        "SELECT payload FROM pos_floor_layout WHERE outlet = ?",
        (outlet,),
    ).fetchone()
    if not row:
        if outlet == POS_OUTLET_BAR:
            return default_bar_pos_floor_payload()
        return empty_pos_floor_payload()
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    areas = parsed.get("areas")
    tables = parsed.get("tables")
    if not isinstance(areas, list) or not isinstance(tables, list):
        return empty_pos_floor_payload()
    return _normalize_pos_floor_payload(areas, tables)


def save_pos_floor_layout(conn, areas, tables, outlet=POS_OUTLET_RESTAURANT):
    """Replace floor layout payload for an outlet."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    payload = _normalize_pos_floor_payload(areas, tables)
    blob = json.dumps(payload, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO pos_floor_layout (outlet, payload, updated_at)
        VALUES (?, ?, {SQL_NOW})
        ON CONFLICT(outlet) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """
    , (outlet, blob))
    return payload


def _new_pos_merge_group_id():
    return f"mg_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.getpid() % 10000:04d}"


def _pos_find_table_by_name(tables, table_label):
    needle = str(table_label or "").strip().lower()
    if not needle:
        return None
    for t in tables or []:
        if str(t.get("name") or "").strip().lower() == needle:
            return t
    return None


def format_pos_merged_table_label(names):
    """Human label for a merged group, e.g. 'Table 1 and Table 2'."""
    clean = []
    seen = set()
    for raw in names or []:
        name = str(raw or "").strip()
        key = name.lower()
        if not name or key in seen:
            continue
        seen.add(key)
        clean.append(name)
    if not clean:
        return ""
    if len(clean) == 1:
        return clean[0]
    if len(clean) == 2:
        return f"{clean[0]} and {clean[1]}"
    return ", ".join(clean[:-1]) + f" and {clean[-1]}"


def link_pos_floor_tables_as_merged(conn, primary_label, member_labels, outlet=POS_OUTLET_RESTAURANT):
    """Visually join floor tables under one merge group.

    ``primary_label`` is the host tile (usually the bill destination). Members
    are hidden on the floor and shown together on the primary as
    \"Table 1 and Table 2\". Returns the updated layout payload.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    primary_name = str(primary_label or "").strip()
    members = []
    for raw in member_labels or []:
        name = str(raw or "").strip()
        if name and name.lower() != primary_name.lower():
            members.append(name)
    if not primary_name:
        raise ValueError("Primary table is required.")
    if not members:
        return get_pos_floor_layout(conn, outlet)

    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    primary = _pos_find_table_by_name(tables, primary_name)
    if not primary:
        raise ValueError(f"Table {primary_name} was not found on the floor.")

    group_ids = set()
    if primary.get("mergeGroupId"):
        group_ids.add(str(primary["mergeGroupId"]))
    member_tiles = []
    for member_name in members:
        tile = _pos_find_table_by_name(tables, member_name)
        if not tile:
            raise ValueError(f"Table {member_name} was not found on the floor.")
        member_tiles.append(tile)
        if tile.get("mergeGroupId"):
            group_ids.add(str(tile["mergeGroupId"]))

    group_id = next(iter(group_ids), None) or _new_pos_merge_group_id()
    involved_ids = {str(primary.get("id") or "")}
    for tile in member_tiles:
        involved_ids.add(str(tile.get("id") or ""))
    if group_ids:
        for t in tables:
            if str(t.get("mergeGroupId") or "") in group_ids:
                involved_ids.add(str(t.get("id") or ""))

    primary_id = str(primary.get("id") or "")
    for t in tables:
        tid = str(t.get("id") or "")
        if tid not in involved_ids:
            continue
        t["mergeGroupId"] = group_id
        t["mergePrimary"] = tid == primary_id

    return save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def unmerge_pos_floor_tables(conn, table_label, outlet=POS_OUTLET_RESTAURANT):
    """Split a visual merge group back into separate floor tiles.

    Does not move or close any open bill — the invoice stays on its current
    ``table_label``. Returns ``{layout, group_names, primary_name, label}``.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    name = str(table_label or "").strip()
    if not name:
        raise ValueError("Table is required.")
    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    tile = _pos_find_table_by_name(tables, name)
    if not tile:
        raise ValueError(f"Table {name} was not found on the floor.")
    group_id = str(tile.get("mergeGroupId") or "").strip()
    if not group_id:
        raise ValueError(f"{name} is not part of a merged group.")

    group_names = []
    primary_name = name
    for t in tables:
        if str(t.get("mergeGroupId") or "") != group_id:
            continue
        group_names.append(str(t.get("name") or "").strip())
        if t.get("mergePrimary"):
            primary_name = str(t.get("name") or "").strip() or primary_name
        t["mergeGroupId"] = None
        t["mergePrimary"] = False

    payload = save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)
    return {
        "layout": payload,
        "group_names": group_names,
        "primary_name": primary_name,
        "label": format_pos_merged_table_label(group_names),
    }


def enrich_pos_floor_tables_for_display(tables):
    """Attach display helpers for merged groups (does not mutate storage shape).

    Room-page pattern: every physical table stays visible. Helpers:

    - ``displayName`` — own table name (group title uses ``mergedNames``)
    - ``mergedNames`` — ordered names in the group
    - ``mergedSeats`` — sum of seats in the group
    - ``billingTableName`` — primary / billing table name
    - ``mergeLabel`` — \"Merged bill\" (primary) or \"Bill: {primary}\" (member)
    - ``hiddenInMerge`` — always False (members are not collapsed away)
    """
    tables = [dict(t) for t in (tables or []) if isinstance(t, dict)]
    by_group = {}
    for t in tables:
        gid = str(t.get("mergeGroupId") or "").strip()
        if not gid:
            own = str(t.get("name") or "").strip()
            t["displayName"] = own
            t["mergedNames"] = [own] if own else []
            t["mergedSeats"] = int(t.get("seats") or 0) or None
            t["billingTableName"] = own
            t["mergeLabel"] = ""
            t["hiddenInMerge"] = False
            continue
        by_group.setdefault(gid, []).append(t)

    for gid, group in by_group.items():
        names = []
        seats_total = 0
        primary = None
        for t in group:
            n = str(t.get("name") or "").strip()
            if n:
                names.append(n)
            try:
                seats_total += max(0, int(t.get("seats") or 0))
            except (TypeError, ValueError):
                pass
            if t.get("mergePrimary"):
                primary = t
        if primary is None and group:
            primary = group[0]
            primary["mergePrimary"] = True
        primary_name = str((primary or {}).get("name") or "").strip()
        others = sorted(
            [n for n in names if n.lower() != primary_name.lower()],
            key=lambda s: s.lower(),
        )
        ordered = ([primary_name] if primary_name else []) + others
        for t in group:
            is_primary = bool(t.get("mergePrimary"))
            own = str(t.get("name") or "").strip()
            t["displayName"] = own
            t["mergedNames"] = ordered
            t["mergedSeats"] = seats_total or None
            t["billingTableName"] = primary_name or own
            t["mergeLabel"] = "Merged bill" if is_primary else (
                f"Bill: {primary_name}" if primary_name else "Merged"
            )
            t["hiddenInMerge"] = False

    return tables


def enrich_pos_floor_tables_with_open_orders(conn, tables, outlet=POS_OUTLET_RESTAURANT):
    """Attach guest names and occupation start from active dine-in bills."""
    tables = [dict(t) for t in (tables or []) if isinstance(t, dict)]
    if not tables:
        return tables

    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    rows = conn.execute(
        """
        SELECT table_label, customer_name, saved_at, created_at
        FROM pos_invoices
        WHERE is_active = 1
          AND status = 'open'
          AND order_type = 'dine_in'
          AND outlet = ?
          AND TRIM(COALESCE(table_label, '')) != ''
          AND COALESCE(customer_bill_sent, 0) = 0
          AND TRIM(COALESCE(customer_bill_at, '')) = ''
        ORDER BY id DESC
        """,
        (outlet,),
    ).fetchall()

    guest_by_table = {}
    occupied_since_by_table = {}
    for row in rows:
        label = str((row["table_label"] if row else "") or "").strip().lower()
        if not label:
            continue
        if label not in guest_by_table:
            name = " ".join(str(row["customer_name"] or "").split()).strip()
            if name and name.casefold() != "guest":
                guest_by_table[label] = name
        if label not in occupied_since_by_table:
            since = str(row["saved_at"] or row["created_at"] or "").strip()
            if since:
                occupied_since_by_table[label] = since
        else:
            since = str(row["saved_at"] or row["created_at"] or "").strip()
            if since and since < occupied_since_by_table[label]:
                occupied_since_by_table[label] = since

    for t in tables:
        status = str(t.get("status") or "available").strip().lower() or "available"
        if status != "occupied":
            t.pop("customerName", None)
            t.pop("customer_name", None)
            t.pop("occupiedSince", None)
            t.pop("occupied_since", None)
            continue
        billing = str(
            t.get("billingTableName") or t.get("name") or ""
        ).strip().lower()
        guest = guest_by_table.get(billing, "")
        if guest:
            t["customerName"] = guest
            t["customer_name"] = guest
        else:
            t.pop("customerName", None)
            t.pop("customer_name", None)
        since = occupied_since_by_table.get(billing, "")
        if not since:
            since = str(t.get("occupiedSince") or t.get("occupied_since") or "").strip()
        if since:
            t["occupiedSince"] = since
        else:
            t.pop("occupiedSince", None)
            t.pop("occupied_since", None)

    return tables


def get_pos_restaurant_settings(conn, outlet=POS_OUTLET_RESTAURANT):
    """Load outlet settings JSON blob (empty dict when unset)."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    row = conn.execute(
        "SELECT payload FROM pos_restaurant_settings WHERE outlet = ?",
        (outlet,),
    ).fetchone()
    if not row:
        return {}
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def save_pos_restaurant_settings(conn, settings, outlet=POS_OUTLET_RESTAURANT):
    """Replace outlet settings JSON."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    if not isinstance(settings, dict):
        settings = {}
    blob = json.dumps(settings, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO pos_restaurant_settings (outlet, payload, updated_at)
        VALUES (?, ?, {SQL_NOW})
        ON CONFLICT(outlet) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """
    , (outlet, blob))
    return settings


# Defaults match long-standing Create Invoice hardcoded rates (percent).
POS_DEFAULT_CGST_PCT = 2.5
POS_DEFAULT_UGST_PCT = 2.5
POS_DEFAULT_VAT_PCT = 10.0


def _pos_line_name_is_banquet(name) -> bool:
    return " ".join(str(name or "").split()).strip().casefold() == "banquet"


def _pos_lines_are_banquet_only(lines) -> bool:
    if not lines:
        return False
    for line in lines:
        if isinstance(line, dict):
            name = line.get("name")
        elif hasattr(line, "keys") and "name" in line.keys():
            name = line["name"]
        else:
            name = ""
        if not _pos_line_name_is_banquet(name):
            return False
    return True


def _parse_pos_tax_override_pct(raw):
    if raw is None:
        return None
    if isinstance(raw, str) and str(raw).strip() == "":
        return None
    try:
        n = float(raw)
    except (TypeError, ValueError):
        return None
    if n != n:
        return None
    if n < 0:
        n = 0.0
    if n > 100:
        n = 100.0
    return round(n, 4)


def _row_tax_override_pct(row, key):
    if not row or key not in row.keys() or row[key] is None:
        return None
    return _parse_pos_tax_override_pct(row[key])


def _pos_settings_panel_values(settings, panel_key):
    """Return the values map for a settings panel (supports legacy array shape)."""
    if not isinstance(settings, dict):
        return {}
    panels = settings.get("panels")
    if not isinstance(panels, dict):
        return {}
    fields = panels.get(panel_key)
    if fields is None:
        return {}
    if isinstance(fields, dict):
        values = fields.get("values")
        if isinstance(values, dict):
            return values
        return {k: v for k, v in fields.items() if k not in ("v", "listboxes")}
    if isinstance(fields, list):
        out = {}
        idx = 0
        for field in fields:
            if not isinstance(field, dict) or field.get("kind") == "listbox":
                continue
            out[f"f{idx}"] = field
            idx += 1
        return out
    return {}


def _pos_settings_checked(values, named_key, legacy_index, default=True):
    """Parse a checkbox field from settings values (named key or legacy fN)."""
    if not isinstance(values, dict):
        return bool(default)
    field = values.get(named_key)
    if field is None:
        field = values.get(f"f{int(legacy_index)}")
    if field is None:
        return bool(default)
    if isinstance(field, dict):
        if "checked" in field:
            return bool(field.get("checked"))
        field = field.get("value")
    if isinstance(field, bool):
        return field
    if isinstance(field, (int, float)) and field == field:
        return bool(field)
    text = str(field or "").strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off", ""):
        return False
    return bool(default)


def _pos_gst_from_inclusive(inclusive_amount, cgst_frac, ugst_frac):
    """Split GST-inclusive food amount into CGST + UGST (does not add tax)."""
    inclusive = _pos_money(inclusive_amount)
    factor = 1.0 + float(cgst_frac or 0) + float(ugst_frac or 0)
    if inclusive <= 0 or factor <= 1:
        return 0.0, 0.0, 0.0
    taxable = _pos_money(inclusive / factor)
    cgst = _pos_money(taxable * float(cgst_frac or 0))
    ugst = _pos_money(inclusive - taxable - cgst)
    if ugst < 0:
        ugst = 0.0
        cgst = _pos_money(inclusive - taxable)
    return cgst, ugst, _pos_money(cgst + ugst)


def _pos_vat_from_inclusive(inclusive_amount, vat_frac):
    """Extract VAT already included in a Bar Alcohol amount."""
    inclusive = _pos_money(inclusive_amount)
    factor = 1.0 + float(vat_frac or 0)
    if inclusive <= 0 or factor <= 1:
        return 0.0
    taxable = _pos_money(inclusive / factor)
    return _pos_money(inclusive - taxable)


def _pos_settings_pct(values, named_key, legacy_index, default_pct):
    """Parse a percent field from settings values (named key or legacy fN)."""
    if not isinstance(values, dict):
        return float(default_pct)
    field = values.get(named_key)
    if field is None:
        field = values.get(f"f{int(legacy_index)}")
    raw = None
    if isinstance(field, dict):
        raw = field.get("value")
    elif field is not None:
        raw = field
    try:
        pct = float(raw)
    except (TypeError, ValueError):
        return float(default_pct)
    if pct != pct or pct < 0:  # NaN / negative
        return float(default_pct)
    if pct > 100:
        pct = 100.0
    return round(pct, 4)


def get_pos_tax_rates(conn, outlet=POS_OUTLET_RESTAURANT):
    """Return CGST/UGST/VAT fractions (0–1) from outlet Taxes settings."""
    settings = get_pos_restaurant_settings(conn, outlet)
    values = _pos_settings_panel_values(settings, "taxes")
    cgst_pct = _pos_settings_pct(values, "cgst_pct", 0, POS_DEFAULT_CGST_PCT)
    ugst_pct = _pos_settings_pct(values, "ugst_pct", 1, POS_DEFAULT_UGST_PCT)
    vat_pct = _pos_settings_pct(values, "vat_pct", 2, POS_DEFAULT_VAT_PCT)
    prices_include_tax = _pos_settings_checked(
        values, "prices_include_tax", 3, True
    )
    return {
        "cgst_pct": cgst_pct,
        "ugst_pct": ugst_pct,
        "vat_pct": vat_pct,
        "cgst": round(cgst_pct / 100.0, 6),
        "ugst": round(ugst_pct / 100.0, 6),
        "vat": round(vat_pct / 100.0, 6),
        "prices_include_tax": bool(prices_include_tax),
    }


POS_INVOICE_ORDER_TYPES = (
    ("dine_in", "Dine In"),
    ("takeaway", "Takeaway"),
    ("delivery", "Delivery"),
)
POS_INVOICE_ORDER_TYPE_LABELS = dict(POS_INVOICE_ORDER_TYPES)

POS_INVOICE_SETTLEMENT_STATUSES = (
    ("settled", "Settled"),
    ("unsettled", "Un Settled"),
)
POS_INVOICE_SETTLEMENT_STATUS_LABELS = dict(POS_INVOICE_SETTLEMENT_STATUSES)


def _pos_money(value, default=0.0):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return float(default)
    if n != n:  # NaN
        return float(default)
    return round(n, 2)


def _normalize_pos_order_type(value):
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("dinein", "dine"):
        key = "dine_in"
    if key not in POS_INVOICE_ORDER_TYPE_LABELS:
        return "dine_in"
    return key


def _parse_discount_line_uids(raw):
    """Return unique line uid strings from JSON array text (or empty list)."""
    text = str(raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        uid = str(item or "").strip()
        if uid and uid not in out:
            out.append(uid)
    return out


def _serialize_discount_line_uids(uids):
    cleaned = []
    for item in uids or []:
        uid = str(item or "").strip()
        if uid and uid not in cleaned:
            cleaned.append(uid)
    return json.dumps(cleaned) if cleaned else ""


def _pos_invoice_line_dicts(conn, invoice_id):
    rows = conn.execute(
        """
        SELECT
            l.id,
            l.sort_order,
            l.menu_item_id,
            l.name,
            l.variant,
            l.rate,
            l.qty,
            l.line_total,
            l.sent_qty,
            l.notes,
            l.line_uid,
            m.outlet AS menu_outlet
        FROM pos_invoice_lines l
        LEFT JOIN pos_menu_items m ON m.id = l.menu_item_id
        WHERE l.invoice_id = ?
        ORDER BY l.sort_order ASC, l.id ASC
        """,
        (int(invoice_id),),
    ).fetchall()
    lines = []
    for idx, row in enumerate(rows):
        qty = _pos_money(row["qty"])
        sent_qty = _pos_money(row["sent_qty"])
        if sent_qty > qty:
            sent_qty = qty
        keys = row.keys()
        notes = (row["notes"] if "notes" in keys else "") or ""
        line_uid = ""
        if "line_uid" in keys:
            line_uid = str(row["line_uid"] or "").strip()
        if not line_uid:
            line_uid = f"L{idx + 1}"
        menu_outlet = "restaurant"
        if "menu_outlet" in keys:
            menu_outlet = normalize_pos_outlet(row["menu_outlet"])
        lines.append(
            {
                "id": int(row["id"]),
                "uid": line_uid,
                "line_uid": line_uid,
                "sort_order": int(row["sort_order"] or 0),
                "menu_item_id": int(row["menu_item_id"]) if row["menu_item_id"] is not None else None,
                "name": row["name"] or "",
                "variant": row["variant"] or "",
                "rate": _pos_money(row["rate"]),
                "qty": qty,
                "line_total": _pos_money(row["line_total"]),
                "sent_qty": sent_qty,
                "notes": str(notes).strip()[:200],
                "outlet": menu_outlet,
            }
        )
    return lines


def _pos_invoice_row_to_dict(conn, row, *, include_lines=False):
    if not row:
        return None
    invoice_id = int(row["id"])
    order_type = _normalize_pos_order_type(row["order_type"])
    item = {
        "id": invoice_id,
        "order_no": row["order_no"] or "",
        "saved_at": row["saved_at"] or "",
        "order_date": row["order_date"] or "",
        "order_type": order_type,
        "order_type_label": POS_INVOICE_ORDER_TYPE_LABELS.get(order_type, order_type),
        "table": row["table_label"] or "",
        "table_label": row["table_label"] or "",
        "captain": row["captain"] or "",
        "customer_name": row["customer_name"] or "",
        "customer_mobile": row["customer_mobile"] or "",
        "notes": row["notes"] or "",
        "discount_type": row["discount_type"] or "pct",
        "discount_value": _pos_money(row["discount_value"]),
        "service_type": row["service_type"] or "pct",
        "service_value": _pos_money(row["service_value"]),
        "tip_amount": _pos_money(row["tip_amount"]),
        "coupon_code": row["coupon_code"] or "",
        "discount_line_uids": _parse_discount_line_uids(
            row["discount_line_uids"] if "discount_line_uids" in row.keys() else ""
        ),
        "discount_reason": (row["discount_reason"] or "")
        if "discount_reason" in row.keys()
        else "",
        "subtotal": _pos_money(row["subtotal"]),
        "discount": _pos_money(row["discount_amount"]),
        "gst": _pos_money(row["gst_amount"]),
        "vat": _pos_money(row["vat_amount"]) if "vat_amount" in row.keys() else 0.0,
        "tax_cgst_pct": _row_tax_override_pct(row, "tax_cgst_pct"),
        "tax_ugst_pct": _row_tax_override_pct(row, "tax_ugst_pct"),
        "service": _pos_money(row["service_amount"]),
        "tip": _pos_money(row["tip"]),
        "round_off": _pos_money(row["round_off"]),
        "grand_total": _pos_money(row["grand_total"]),
        "created_by": row["created_by"] or "",
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "status": row["status"] or "open",
        "settled_at": (row["settled_at"] or "") if "settled_at" in row.keys() else "",
        "payment_notes": (row["payment_notes"] or "") if "payment_notes" in row.keys() else "",
        "kot_sent": bool(row["kot_sent"]),
        "first_kot_at": row["first_kot_at"] or "",
        "kot_no": (row["kot_no"] or "").strip() if "kot_no" in row.keys() else "",
        "customer_bill_sent": bool(row["customer_bill_sent"]) if "customer_bill_sent" in row.keys() else False,
        "customer_bill_at": (row["customer_bill_at"] or "") if "customer_bill_at" in row.keys() else "",
        "cancel_reason": (row["cancel_reason"] or "") if "cancel_reason" in row.keys() else "",
        "cancelled_at": (row["cancelled_at"] or "") if "cancelled_at" in row.keys() else "",
        "cancelled_by": (row["cancelled_by"] or "").strip() if "cancelled_by" in row.keys() else "",
        "stock_deducted_at": (row["stock_deducted_at"] or "") if "stock_deducted_at" in row.keys() else "",
        "outlet": normalize_pos_outlet(row["outlet"]) if "outlet" in row.keys() else POS_OUTLET_RESTAURANT,
        "item_count": int(row["item_count"]) if "item_count" in row.keys() else 0,
        "payment_modes": [],
        "payment_mode_label": _pos_invoice_payment_mode_label(
            {"status": row["status"] or "open"}
        ),
        "payment_amounts": _empty_pos_payment_amounts(),
    }
    if include_lines:
        item["lines"] = _pos_invoice_line_dicts(conn, invoice_id)
        if not item["item_count"]:
            item["item_count"] = len(item["lines"])
    return item


def _pos_payment_mode_labels_from_methods(methods):
    """Unique display labels in settlement order (Cash + UPI, etc.)."""
    labels = []
    seen = set()
    for raw in methods or []:
        key = _normalize_pos_payment_method(raw) or str(raw or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        labels.append(POS_PAYMENT_METHOD_LABELS.get(key, key.replace("_", " ").title()))
    return labels


def _pos_fb_invoice_numbers_by_order_no(conn, order_nos):
    """Map POS order numbers to minted FBE invoices via linkedPosOrders."""
    needles = []
    seen = set()
    for raw in order_nos or []:
        order_no = str(raw or "").strip()
        if not order_no or order_no in seen:
            continue
        seen.add(order_no)
        needles.append(order_no)
    if not needles:
        return {}
    ensure_hotel_room_invoices_schema(conn)
    like_clauses = []
    params = [HOTEL_INVOICE_SOURCE_FB_COMBINED]
    for order_no in needles:
        like_clauses.append("payload_json LIKE ?")
        params.append("%" + order_no + "%")
    rows = conn.execute(
        f"""
        SELECT invoice_number, payload_json
        FROM hotel_room_invoices
        WHERE source = ?
          AND lower(COALESCE(status, '')) != 'cancelled'
          AND ({" OR ".join(like_clauses)})
        """,
        params,
    ).fetchall()
    mapping = {}
    wanted = set(needles)
    for row in rows:
        fb_no = str(row["invoice_number"] or "").strip()
        if not fb_no:
            continue
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        linked = payload.get("linkedPosOrders") or payload.get("linked_pos_orders") or []
        stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
        candidates = list(linked)
        folio = stay.get("folioCharges") or stay.get("folio_charges") or []
        if isinstance(folio, list):
            candidates.extend(folio)
        for item in candidates:
            if not isinstance(item, dict):
                continue
            order_no = str(item.get("orderNo") or item.get("order_no") or "").strip()
            if order_no in wanted and order_no not in mapping:
                mapping[order_no] = fb_no
    return mapping


def _pos_room_number_for_hotel_room_id(conn, hotel_room_id):
    """Return display room number for an occupied (or known) hotel room id."""
    hotel_room_id = str(hotel_room_id or "").strip()
    if not hotel_room_id:
        return ""
    layout = get_hotel_rooms_layout(conn)
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        if str(room.get("id") or "") != hotel_room_id and str(
            room.get("number") or ""
        ) != hotel_room_id:
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
        return str(
            stay.get("mergeRoomLabel")
            or stay.get("merge_room_label")
            or room.get("number")
            or ""
        ).strip()
    return ""


def _pos_payment_notes_with_room_number(notes, room_number):
    """Embed destination room on the payment row so ledger labels stay durable."""
    base = str(notes or "").strip()
    room_number = str(room_number or "").strip()
    if not room_number:
        return base
    tag = f"hotel_room_number={room_number}"
    if tag in base:
        return base
    return f"{base}\n{tag}".strip() if base else tag


def _pos_room_number_from_payment_notes(notes):
    for line in str(notes or "").splitlines():
        line = line.strip()
        if line.lower().startswith("hotel_room_number="):
            return line.split("=", 1)[1].strip()
    return ""


def _pos_room_transfer_room_numbers_by_order_no(conn, order_nos, invoice_ids=None):
    """Map POS order numbers to the hotel room they were transferred onto."""
    needles = []
    seen = set()
    for raw in order_nos or []:
        order_no = str(raw or "").strip()
        if not order_no or order_no in seen:
            continue
        seen.add(order_no)
        needles.append(order_no)
    if not needles:
        return {}
    mapping = {}
    ensure_hotel_room_invoices_schema(conn)
    placeholders = ",".join("?" for _ in needles)
    pos_placeholders = ",".join("lower(?)" for _ in needles)
    rows = conn.execute(
        f"""
        SELECT invoice_number, room_number, payload_json
        FROM hotel_room_invoices
        WHERE source = ?
          AND (
            invoice_number IN ({placeholders})
            OR lower(trim(COALESCE(json_extract(payload_json, '$.posOrderNo'), '')))
               IN ({pos_placeholders})
          )
        """,
        [HOTEL_INVOICE_SOURCE_POS_TRANSFER, *needles, *needles],
    ).fetchall()
    needle_set = {n.lower() for n in needles}
    for row in rows:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        pos_order = str(payload.get("posOrderNo") or "").strip()
        inv_no = str(row["invoice_number"] or "").strip()
        order_no = ""
        if pos_order and pos_order.lower() in needle_set:
            order_no = pos_order
        elif inv_no and inv_no.lower() in needle_set:
            order_no = inv_no
        if not order_no:
            continue
        room_no = str(row["room_number"] or "").strip()
        if not room_no:
            room_no = str(payload.get("number") or "").strip()
            stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
            if not room_no:
                room_no = str(
                    stay.get("mergeRoomLabel")
                    or stay.get("merge_room_label")
                    or ""
                ).strip()
        if order_no and room_no and order_no not in mapping:
            mapping[order_no] = room_no

    missing = [n for n in needles if n not in mapping]
    invoice_id_set = set()
    for raw in invoice_ids or []:
        try:
            invoice_id_set.add(str(int(raw)))
        except (TypeError, ValueError):
            continue
    if missing or invoice_id_set:
        wanted = set(missing)
        layout = get_hotel_rooms_layout(conn)
        for room in layout.get("rooms") or []:
            if not isinstance(room, dict):
                continue
            stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
            room_no = str(
                stay.get("mergeRoomLabel")
                or stay.get("merge_room_label")
                or room.get("number")
                or ""
            ).strip()
            if not room_no:
                continue
            folio = stay.get("folioCharges") or stay.get("folio_charges") or []
            if not isinstance(folio, list):
                continue
            for line in folio:
                if not isinstance(line, dict):
                    continue
                kind = str(line.get("kind") or "").strip().lower()
                if kind not in ("restaurant_room_transfer", "bar_room_transfer", "other"):
                    continue
                order_no = str(line.get("orderNo") or line.get("order_no") or "").strip()
                inv_id = str(
                    line.get("invoiceId") or line.get("invoice_id") or ""
                ).strip()
                if order_no in wanted and order_no not in mapping:
                    mapping[order_no] = room_no
                elif inv_id and inv_id in invoice_id_set and order_no and order_no not in mapping:
                    mapping[order_no] = room_no
    return mapping


def _annotate_pos_room_transfer_labels(labels, fb_invoice_number="", room_number=""):
    """Attach room + FBE number or pending note to Room Transfer payment labels."""
    fb_no = str(fb_invoice_number or "").strip()
    room_no = str(room_number or "").strip()
    annotated = []
    for lab in labels or []:
        if lab == "Room Transfer":
            if room_no and fb_no:
                annotated.append(f"Room Transfer · {room_no} ({fb_no})")
            elif room_no:
                annotated.append(
                    f"Room Transfer · {room_no} (Invoice yet to generate)"
                )
            elif fb_no:
                annotated.append(f"Room Transfer ({fb_no})")
            else:
                annotated.append("Room Transfer (Invoice yet to generate)")
        else:
            annotated.append(lab)
    return annotated


def _pos_invoice_payment_mode_label(
    invoice, labels=None, fb_invoice_number="", room_number=""
):
    """Ledger Payment Mode column: payments, else Cancelled / Unsettled from status."""
    labels = _annotate_pos_room_transfer_labels(
        list(labels or []),
        fb_invoice_number=fb_invoice_number,
        room_number=room_number,
    )
    if labels:
        return " + ".join(labels)
    status = str((invoice or {}).get("status") or "open").strip().lower() or "open"
    if status == "cancelled":
        return "Cancelled"
    if status == "closed":
        return "Settled"
    return "Unsettled"


def _apply_pos_invoice_payment_modes(conn, invoice):
    """Attach payment_modes / payment_mode_label / payment_amounts from payments."""
    if not invoice or not invoice.get("id"):
        return invoice
    payments = list_pos_invoice_payments(conn, invoice["id"])
    # Ignore ₹0 tender rows (auto-settled complimentary / historical imports) so
    # Payment Mode shows Settled for closed zero-payable bills, not "Cash".
    tender_payments = [
        p for p in payments if _pos_money((p or {}).get("amount")) > 0.009
    ]
    methods = [p.get("payment_method") for p in tender_payments]
    labels = _pos_payment_mode_labels_from_methods(methods)
    unique_modes = []
    seen = set()
    for raw in methods:
        key = _normalize_pos_payment_method(raw) or str(raw or "").strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique_modes.append(key)
    fb_no = ""
    room_no = ""
    if "room_transfer" in unique_modes:
        order_no = str(invoice.get("order_no") or "").strip()
        fb_map = _pos_fb_invoice_numbers_by_order_no(conn, [order_no] if order_no else [])
        fb_no = fb_map.get(order_no, "")
        room_map = _pos_room_transfer_room_numbers_by_order_no(
            conn,
            [order_no] if order_no else [],
            invoice_ids=[invoice.get("id")],
        )
        room_no = room_map.get(order_no, "")
        if not room_no:
            for pay in payments:
                key = _normalize_pos_payment_method(pay.get("payment_method"))
                if key != "room_transfer":
                    continue
                room_no = _pos_room_number_from_payment_notes(pay.get("notes"))
                if room_no:
                    break
        if not room_no:
            hotel_room = invoice.get("hotel_room")
            if isinstance(hotel_room, dict):
                stay = (
                    hotel_room.get("stay")
                    if isinstance(hotel_room.get("stay"), dict)
                    else {}
                )
                room_no = str(
                    stay.get("mergeRoomLabel")
                    or stay.get("merge_room_label")
                    or hotel_room.get("number")
                    or ""
                ).strip()
    invoice["payment_modes"] = unique_modes
    invoice["payment_mode_label"] = _pos_invoice_payment_mode_label(
        invoice, labels, fb_invoice_number=fb_no, room_number=room_no
    )
    invoice["payment_amounts"] = _pos_payment_amounts_from_rows(payments)
    return invoice


def _enrich_pos_invoices_payment_modes(conn, invoices):
    """Batch-fill payment mode labels and per-method amounts for ledger lists."""
    ensure_pos_schema(conn)
    rows = list(invoices or [])
    if not rows:
        return rows
    ids = [int(inv["id"]) for inv in rows if inv and inv.get("id") is not None]
    if not ids:
        return rows
    placeholders = ",".join("?" for _ in ids)
    pay_rows = conn.execute(
        f"""
        SELECT invoice_id, payment_method, amount, notes
        FROM pos_invoice_payments
        WHERE invoice_id IN ({placeholders})
        ORDER BY id ASC
        """,
        ids,
    ).fetchall()
    methods_by_id = {}
    amounts_by_id = {}
    notes_by_id = {}
    for pay in pay_rows:
        inv_id = int(pay["invoice_id"])
        amounts_by_id.setdefault(inv_id, []).append(pay)
        notes_by_id.setdefault(inv_id, []).append(pay["notes"] or "")
        # Skip ₹0 tender so zero-payable closed bills label as Settled.
        if _pos_money(pay["amount"]) <= 0.009:
            continue
        methods_by_id.setdefault(inv_id, []).append(pay["payment_method"])
    transfer_order_nos = []
    prepared = []
    for inv in rows:
        inv_id = int(inv["id"])
        methods = methods_by_id.get(inv_id, [])
        labels = _pos_payment_mode_labels_from_methods(methods)
        unique_modes = []
        seen = set()
        for raw in methods:
            key = _normalize_pos_payment_method(raw) or str(raw or "").strip().lower()
            if not key or key in seen:
                continue
            seen.add(key)
            unique_modes.append(key)
        inv["payment_modes"] = unique_modes
        inv["payment_amounts"] = _pos_payment_amounts_from_rows(
            amounts_by_id.get(inv_id, [])
        )
        order_no = str(inv.get("order_no") or "").strip()
        if "room_transfer" in unique_modes and order_no:
            transfer_order_nos.append(order_no)
        prepared.append((inv, labels, unique_modes, order_no, inv_id))
    fb_map = _pos_fb_invoice_numbers_by_order_no(conn, transfer_order_nos)
    room_map = _pos_room_transfer_room_numbers_by_order_no(
        conn, transfer_order_nos, invoice_ids=ids
    )
    for inv, labels, unique_modes, order_no, inv_id in prepared:
        fb_no = fb_map.get(order_no, "") if "room_transfer" in unique_modes else ""
        room_no = room_map.get(order_no, "") if "room_transfer" in unique_modes else ""
        if "room_transfer" in unique_modes and not room_no:
            for note in notes_by_id.get(inv_id, []):
                room_no = _pos_room_number_from_payment_notes(note)
                if room_no:
                    break
        inv["payment_mode_label"] = _pos_invoice_payment_mode_label(
            inv, labels, fb_invoice_number=fb_no, room_number=room_no
        )
    return rows


def _pos_floor_table_status(layout, table_label):
    """Case-insensitive floor status lookup for a table name; None when not on the floor."""
    needle = str(table_label or "").strip().lower()
    if not needle:
        return None
    for t in (layout or {}).get("tables") or []:
        if str(t.get("name") or "").strip().lower() == needle:
            return str(t.get("status") or "available").strip().lower() or "available"
    return None


def _pos_mark_table_occupied(conn, table_label, outlet=POS_OUTLET_RESTAURANT):
    """Flip a table to occupied when a dine-in bill claims it (save / autosave / KOT).

    Best-effort: only advances tables that are currently available — never
    overrides reserved/cleaning/inactive set deliberately from the Tables page.
    """
    needle = str(table_label or "").strip().lower()
    if not needle:
        return
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    changed = False
    for t in tables:
        if str(t.get("name") or "").strip().lower() == needle:
            if str(t.get("status") or "available").strip().lower() in ("", "available"):
                t["status"] = "occupied"
                changed = True
            break
    if changed:
        save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def _pos_mark_table_available(conn, table_label, outlet=POS_OUTLET_RESTAURANT):
    """Free a table back to available — used when a bill is explicitly closed.
    Unlike _pos_mark_table_occupied this is an unconditional override: closing a
    bill is a deliberate staff action, so it wins over whatever status the table
    was showing."""
    needle = str(table_label or "").strip().lower()
    if not needle:
        return
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    changed = False
    for t in tables:
        if str(t.get("name") or "").strip().lower() == needle:
            if str(t.get("status") or "").strip().lower() != "available":
                t["status"] = "available"
                changed = True
            break
    if changed:
        save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def sync_pos_floor_occupancy_from_open_orders(conn, outlet=POS_OUTLET_RESTAURANT):
    """Align floor tiles with active (pre-invoice) dine-in bills.

    - Available → Occupied when an open bill exists that has not yet had its
      customer invoice generated.
    - Occupied → Available when no such bill exists (repairs stale tiles after
      Generate Invoice, table moves, closes, or bad saves). Reserved / cleaning /
      inactive are never changed.

    Once Generate Invoice (customer_bill_sent) runs, the table is free for the
    next party even if Settle Bill is still pending. Reopened ledger edits keep
    customer_bill_at set, so they never reclaim the floor tile.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    rows = conn.execute(
        """
        SELECT DISTINCT table_label
        FROM pos_invoices
        WHERE is_active = 1
          AND status = 'open'
          AND order_type = 'dine_in'
          AND outlet = ?
          AND TRIM(COALESCE(table_label, '')) != ''
          AND COALESCE(customer_bill_sent, 0) = 0
          AND TRIM(COALESCE(customer_bill_at, '')) = ''
        """,
        (outlet,),
    ).fetchall()
    occupied_labels = set()
    for row in rows:
        label = str((row["table_label"] if row else "") or "").strip()
        if not label:
            continue
        occupied_labels.add(label.lower())
        _pos_mark_table_occupied(conn, label, outlet)

    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    changed = False
    for t in tables:
        name = str(t.get("name") or "").strip()
        if not name:
            continue
        status = str(t.get("status") or "available").strip().lower() or "available"
        if status != "occupied":
            continue
        if name.lower() not in occupied_labels:
            t["status"] = "available"
            changed = True
    if changed:
        save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def get_open_pos_invoice_for_table(conn, table_label, outlet=POS_OUTLET_RESTAURANT):
    """Return the most recent active (pre-invoice) open dine-in bill for a table.

    Invoices that already had Generate Invoice (customer_bill_sent) no longer
    claim the table — settle continues from the locked bill / ledger, while the
    floor tile is free for a new party.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    needle = str(table_label or "").strip()
    if not needle:
        return None
    row = conn.execute(
        """
        SELECT
            i.*,
            (
                SELECT COUNT(*) FROM pos_invoice_lines l WHERE l.invoice_id = i.id
            ) AS item_count
        FROM pos_invoices i
        WHERE i.is_active = 1
          AND i.status = 'open'
          AND i.order_type = 'dine_in'
          AND i.outlet = ?
          AND LOWER(i.table_label) = LOWER(?)
          AND COALESCE(i.customer_bill_sent, 0) = 0
          AND TRIM(COALESCE(i.customer_bill_at, '')) = ''
        ORDER BY i.id DESC
        LIMIT 1
        """,
        (outlet, needle),
    ).fetchone()
    return _pos_invoice_row_to_dict(conn, row, include_lines=True)


def transfer_pos_invoice_table(conn, from_table, to_table, outlet=POS_OUTLET_RESTAURANT):
    """Move an open dine-in bill from one floor table to another available table.

    Updates ``pos_invoices.table_label``, frees the source tile, and marks the
    destination occupied. Raises ``ValueError`` with a staff-facing message on
    validation failure.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    from_label = str(from_table or "").strip()
    to_label = str(to_table or "").strip()
    if not from_label:
        raise ValueError("Source table is required.")
    if not to_label:
        raise ValueError("Destination table is required.")
    if from_label.lower() == to_label.lower():
        raise ValueError("Choose a different destination table.")

    invoice = get_open_pos_invoice_for_table(conn, from_label, outlet)
    if not invoice:
        raise ValueError(f"No open bill on {from_label}.")

    if get_open_pos_invoice_for_table(conn, to_label, outlet):
        raise ValueError(f"{to_label} already has an open bill.")

    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    dest = None
    for t in tables:
        if str(t.get("name") or "").strip().lower() == to_label.lower():
            dest = t
            break
    if not dest:
        raise ValueError(f"Table {to_label} was not found on the floor.")
    dest_status = str(dest.get("status") or "available").strip().lower() or "available"
    if dest_status == "blocked":
        dest_status = "inactive"
    if dest_status != "available":
        raise ValueError(f"{to_label} is not available.")

    to_canonical = str(dest.get("name") or to_label).strip()
    from_canonical = str(invoice.get("table_label") or from_label).strip()

    conn.execute(
        "UPDATE pos_invoices SET table_label = ? WHERE id = ?",
        (to_canonical, int(invoice["id"])),
    )
    _pos_mark_table_available(conn, from_canonical, outlet)
    _pos_mark_table_occupied(conn, to_canonical, outlet)
    return get_pos_invoice(conn, int(invoice["id"]))


def _recompute_pos_invoice_money_from_lines(conn, invoice_id):
    """Recalculate subtotal/discount/gst/vat/service/tip/total from current lines.

    Uses the destination invoice's stored discount/service/tip settings.
    Menu selling prices are GST-inclusive by default (Taxes → Prices include tax):
    CGST/UGST/VAT are extracted from line totals, not added on top.
    Round half to nearest rupee — same rule as the Create Invoice UI.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        """
        SELECT id, outlet, discount_type, discount_value, service_type, service_value, tip, tip_amount,
               discount_line_uids, tax_cgst_pct, tax_ugst_pct
        FROM pos_invoices
        WHERE id = ? AND is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")

    line_rows = conn.execute(
        """
        SELECT l.name, l.rate, l.qty, l.menu_item_id, l.variant, l.line_uid, c.name AS category_name,
               i.item_kind, i.menu_type, i.outlet AS menu_outlet
        FROM pos_invoice_lines l
        LEFT JOIN pos_menu_items i ON i.id = l.menu_item_id
        LEFT JOIN pos_menu_categories c ON c.id = i.category_id
        WHERE l.invoice_id = ?
        """,
        (invoice_id,),
    ).fetchall()
    subtotal = 0.0
    bar_alcohol_subtotal = 0.0
    scoped_uids = set(
        _parse_discount_line_uids(
            row["discount_line_uids"] if "discount_line_uids" in row.keys() else ""
        )
    )
    discount_base = 0.0
    for line in line_rows:
        line_total = _pos_money(line["rate"]) * _pos_money(line["qty"])
        subtotal += line_total
        line_uid = ""
        if "line_uid" in line.keys() and line["line_uid"]:
            line_uid = str(line["line_uid"] or "").strip()
        if not scoped_uids or (line_uid and line_uid in scoped_uids):
            discount_base += line_total
        keys = line.keys()
        menu_outlet = "restaurant"
        if "menu_outlet" in keys and line["menu_outlet"]:
            menu_outlet = normalize_pos_outlet(line["menu_outlet"])
        kind = ""
        if "item_kind" in keys and line["item_kind"]:
            kind = str(line["item_kind"] or "").strip().lower()
        if kind in ("liquour", "alcohol", "bar"):
            kind = "liquor"
        menu_type = ""
        if "menu_type" in keys and line["menu_type"]:
            menu_type = str(line["menu_type"] or "").strip().lower()
        if menu_type in ("liquour", "alcohol"):
            menu_type = "liquor"
        cat = ""
        if "category_name" in keys and line["category_name"]:
            cat = line["category_name"]
        elif line["variant"]:
            cat = line["variant"]
        is_liquor = kind == "liquor" or menu_type == "liquor" or is_pos_liquor_category(cat)
        if menu_outlet == POS_OUTLET_BAR and is_liquor:
            bar_alcohol_subtotal += line_total
    subtotal = _pos_money(subtotal)
    bar_alcohol_subtotal = _pos_money(bar_alcohol_subtotal)
    discount_base = _pos_money(discount_base if scoped_uids else subtotal)

    discount_type = str(row["discount_type"] or "pct").strip().lower() or "pct"
    service_type = str(row["service_type"] or "pct").strip().lower() or "pct"
    discount_value = _pos_money(row["discount_value"])
    service_value = _pos_money(row["service_value"])
    tip = _pos_money(row["tip"] if row["tip"] is not None else row["tip_amount"])

    if discount_type == "inr":
        discount = min(max(0.0, discount_base), max(0.0, discount_value))
        discount = min(discount, max(0.0, subtotal))
    else:
        pct = min(100.0, max(0.0, discount_value))
        discount = _pos_money(max(0.0, discount_base) * (pct / 100.0))
        discount = min(discount, max(0.0, subtotal))
    after_discount = max(0.0, subtotal - discount)
    bar_share = (bar_alcohol_subtotal / subtotal) if subtotal > 0 else 0.0
    bar_after = _pos_money(after_discount * bar_share)
    food_after = max(0.0, after_discount - bar_after)
    inv_outlet = normalize_pos_outlet(row["outlet"] if "outlet" in row.keys() else None)
    rates = get_pos_tax_rates(conn, inv_outlet)
    banquet_only = _pos_lines_are_banquet_only(line_rows)
    tax_cgst_pct = _row_tax_override_pct(row, "tax_cgst_pct") if banquet_only else None
    tax_ugst_pct = _row_tax_override_pct(row, "tax_ugst_pct") if banquet_only else None
    cgst_frac = (tax_cgst_pct / 100.0) if tax_cgst_pct is not None else rates["cgst"]
    ugst_frac = (tax_ugst_pct / 100.0) if tax_ugst_pct is not None else rates["ugst"]
    if rates.get("prices_include_tax", True):
        food_gross = _pos_money(max(0.0, subtotal - bar_alcohol_subtotal))
        _g_cgst, _g_ugst, gst_gross = _pos_gst_from_inclusive(
            food_gross, cgst_frac, ugst_frac
        )
        vat_gross = _pos_vat_from_inclusive(bar_alcohol_subtotal, rates["vat"])
        taxable_gross = _pos_money(
            food_gross - gst_gross + bar_alcohol_subtotal - vat_gross
        )
        _n_cgst, _n_ugst, gst = _pos_gst_from_inclusive(
            food_after, cgst_frac, ugst_frac
        )
        vat = _pos_vat_from_inclusive(bar_after, rates["vat"])
        taxable_net = _pos_money(food_after - gst + bar_after - vat)
        discount = _pos_money(taxable_gross - taxable_net)
        subtotal = taxable_gross
        tax_add = 0.0
    else:
        gst = _pos_money(food_after * (cgst_frac + ugst_frac))
        vat = _pos_money(bar_after * rates["vat"])
        tax_add = gst + vat
    if service_type == "inr":
        service = min(max(0.0, after_discount), max(0.0, service_value))
    else:
        pct = min(100.0, max(0.0, service_value))
        service = _pos_money(max(0.0, after_discount) * (pct / 100.0))
    tip = max(0.0, tip)
    before_round = after_discount + tax_add + service + tip
    rounded = float(round(before_round))
    round_off = _pos_money(rounded - before_round)
    grand_total = _pos_money(rounded)

    conn.execute(
        f"""
        UPDATE pos_invoices SET
            subtotal = ?,
            discount_amount = ?,
            gst_amount = ?,
            vat_amount = ?,
            service_amount = ?,
            tip = ?,
            tip_amount = ?,
            round_off = ?,
            grand_total = ?,
            tax_cgst_pct = ?,
            tax_ugst_pct = ?,
            updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (
            subtotal,
            discount,
            gst,
            vat,
            service,
            tip,
            tip,
            round_off,
            grand_total,
            tax_cgst_pct,
            tax_ugst_pct,
            invoice_id,
        ),
    )
    return get_pos_invoice(conn, invoice_id)


def merge_pos_invoice_tables(conn, from_table, to_table, outlet=POS_OUTLET_RESTAURANT):
    """Merge two floor tables onto the destination (“Merge into”).

    - Both have open bills: combine lines onto dest, soft-delete source, free
      source tile, then visually join the tiles.
    - Only source has an open bill: move that invoice onto dest, free source,
      occupy dest, then visually join.
    - Only dest has an open bill (or neither): visually join the tiles under
      the destination host — no bill move required.

    Always creates/updates a floor ``mergeGroupId`` so the UI shows
    \"Table 1 and Table 2\". Returns the resulting open invoice dict, or
    ``None`` when the merge was visual-only (no open bill on either table).
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    from_label = str(from_table or "").strip()
    to_label = str(to_table or "").strip()
    if not from_label:
        raise ValueError("Source table is required.")
    if not to_label:
        raise ValueError("Destination table is required.")
    if from_label.lower() == to_label.lower():
        raise ValueError("Choose a different destination table.")

    source = get_open_pos_invoice_for_table(conn, from_label, outlet)
    dest = get_open_pos_invoice_for_table(conn, to_label, outlet)

    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    dest_tile = None
    source_tile = None
    for t in tables:
        name = str(t.get("name") or "").strip()
        if name.lower() == to_label.lower():
            dest_tile = t
        if name.lower() == from_label.lower():
            source_tile = t
    if not dest_tile:
        raise ValueError(f"Table {to_label} was not found on the floor.")
    if not source_tile:
        raise ValueError(f"Table {from_label} was not found on the floor.")

    to_canonical = str(dest_tile.get("name") or to_label).strip()
    from_canonical = str(source_tile.get("name") or from_label).strip()

    # Visual-only (or dest already holds the only bill): join tiles, keep bill.
    if not source:
        link_pos_floor_tables_as_merged(conn, to_canonical, [from_canonical], outlet)
        if dest:
            return get_pos_invoice(conn, int(dest["id"]))
        return None

    from_canonical = str(source.get("table_label") or from_canonical).strip()
    source_id = int(source["id"])

    # Empty destination: move the whole source invoice onto that table.
    if not dest:
        conn.execute(
            "UPDATE pos_invoices SET table_label = ? WHERE id = ?",
            (to_canonical, source_id),
        )
        _pos_mark_table_available(conn, from_canonical, outlet)
        _pos_mark_table_occupied(conn, to_canonical, outlet)
        try:
            link_pos_floor_tables_as_merged(conn, to_canonical, [from_canonical], outlet)
        except ValueError:
            pass
        return get_pos_invoice(conn, source_id)

    dest_id = int(dest["id"])
    if source_id == dest_id:
        raise ValueError("Choose a different destination table.")

    max_sort = conn.execute(
        "SELECT COALESCE(MAX(sort_order), 0) AS m FROM pos_invoice_lines WHERE invoice_id = ?",
        (dest_id,),
    ).fetchone()
    sort_base = int(max_sort["m"] if max_sort else 0)

    source_lines = conn.execute(
        """
        SELECT id, sort_order
        FROM pos_invoice_lines
        WHERE invoice_id = ?
        ORDER BY sort_order ASC, id ASC
        """,
        (source_id,),
    ).fetchall()
    for idx, line in enumerate(source_lines, start=1):
        conn.execute(
            """
            UPDATE pos_invoice_lines
            SET invoice_id = ?, sort_order = ?
            WHERE id = ?
            """,
            (dest_id, sort_base + idx, int(line["id"])),
        )

    src_notes = str(source.get("notes") or "").strip()
    dest_notes = str(dest.get("notes") or "").strip()
    if src_notes:
        merged_notes = (
            f"{dest_notes}\n[Merged from {from_canonical}] {src_notes}".strip()
            if dest_notes
            else f"[Merged from {from_canonical}] {src_notes}"
        )
        conn.execute(
            "UPDATE pos_invoices SET notes = ? WHERE id = ?",
            (merged_notes[:2000], dest_id),
        )

    soft_delete_pos_invoice(conn, source_id)
    _pos_mark_table_available(conn, from_canonical, outlet)
    _pos_mark_table_occupied(conn, to_canonical, outlet)
    try:
        link_pos_floor_tables_as_merged(conn, to_canonical, [from_canonical], outlet)
    except ValueError:
        pass
    return _recompute_pos_invoice_money_from_lines(conn, dest_id)


def list_pos_kot_pending_summary(conn, outlet=POS_OUTLET_RESTAURANT):
    """Open dine-in orders with unsents (qty > sent_qty) — same rule as the
    invoice page KOT pending check. Powers the Tables page Kitchen Orders
    Pending banner and details modal.

    Includes tables with a plain save (kot_sent=0, sent_qty=0) and Occupied
    tables with later qty bumps — occupancy / kot_sent is intentionally not a
    filter here.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
    floor_by_name = {}
    for t in (layout or {}).get("tables") or []:
        key = str(t.get("name") or "").strip().lower()
        if key:
            floor_by_name[key] = t

    rows = conn.execute(
        """
        SELECT
            i.id AS invoice_id,
            i.order_no AS order_no,
            i.table_label AS name,
            i.saved_at AS saved_at,
            i.updated_at AS updated_at,
            i.first_kot_at AS first_kot_at,
            COALESCE(i.kot_no, '') AS kot_no,
            COUNT(l.id) AS pending_items,
            COALESCE(SUM(l.qty - COALESCE(l.sent_qty, 0)), 0) AS pending_qty
        FROM pos_invoices i
        JOIN pos_invoice_lines l
          ON l.invoice_id = i.id
         AND l.qty > COALESCE(l.sent_qty, 0)
        WHERE i.is_active = 1
          AND i.status = 'open'
          AND i.order_type = 'dine_in'
          AND i.outlet = ?
          AND TRIM(COALESCE(i.table_label, '')) != ''
        GROUP BY i.id, i.order_no, i.table_label, i.saved_at, i.updated_at, i.first_kot_at, i.kot_no
        ORDER BY i.id ASC
        """,
        (outlet,),
    ).fetchall()
    tables = []
    pending_item_count = 0
    for row in rows:
        pending_items = int(row["pending_items"] or 0)
        pending_qty = int(float(row["pending_qty"] or 0))
        pending_item_count += pending_items
        name = (row["name"] or "").strip()
        floor = floor_by_name.get(name.lower()) or {}
        seats = floor.get("seats")
        try:
            seats = int(seats) if seats is not None and str(seats).strip() != "" else None
        except (TypeError, ValueError):
            seats = None
        table_status = str(floor.get("status") or "available").strip().lower() or "available"
        order_no = (row["order_no"] or "").strip()
        kot_no = pos_kot_display_no(order_no, row["kot_no"] if "kot_no" in row.keys() else "")
        first_kot = (row["first_kot_at"] or "").strip()
        saved_at = (row["saved_at"] or "").strip()
        updated_at = (row["updated_at"] or "").strip()
        pending_since = (updated_at if first_kot else saved_at) or saved_at or updated_at
        tables.append(
            {
                "name": name,
                "invoice_id": int(row["invoice_id"]),
                "order_no": order_no,
                "kot_no": kot_no,
                "pending_items": pending_items,
                "pending_qty": pending_qty,
                "seats": seats,
                "table_status": table_status,
                "saved_at": pending_since,
                "pending_since": pending_since,
            }
        )
    return {
        "pending_table_count": len(tables),
        "pending_item_count": pending_item_count,
        "tables": tables,
    }


def send_pos_invoice_pending_kot(conn, invoice_id):
    """Mark every unsent line qty as sent for an open invoice (Tables KOT modal).

    Returns the updated invoice dict. Raises ValueError when there is nothing to send.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc

    row = conn.execute(
        """
        SELECT id, order_no, table_label, order_type, kot_sent, first_kot_at, kot_no, status, outlet, order_date
        FROM pos_invoices
        WHERE id = ? AND is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    if str(row["status"] or "").strip().lower() != "open":
        raise ValueError("Only open invoices can be sent to kitchen.")

    pending = conn.execute(
        """
        SELECT id, qty, COALESCE(sent_qty, 0) AS sent_qty
        FROM pos_invoice_lines
        WHERE invoice_id = ?
          AND qty > COALESCE(sent_qty, 0)
        """,
        (invoice_id,),
    ).fetchall()
    if not pending:
        raise ValueError("Nothing new to send — kitchen is already up to date.")

    for line in pending:
        conn.execute(
            "UPDATE pos_invoice_lines SET sent_qty = ? WHERE id = ?",
            (float(line["qty"] or 0), int(line["id"])),
        )

    first_kot_at = (row["first_kot_at"] or "").strip()
    is_first_kot = not first_kot_at
    if is_first_kot:
        first_kot_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        f"""
        UPDATE pos_invoices
        SET kot_sent = 1,
            first_kot_at = ?,
            updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (first_kot_at, invoice_id),
    )
    if is_first_kot or not str(row["kot_no"] or "").strip():
        ensure_pos_invoice_kot_no(
            conn,
            invoice_id,
            outlet=row["outlet"] if "outlet" in row.keys() else None,
            order_date=row["order_date"] if "order_date" in row.keys() else None,
        )

    table_label = (row["table_label"] or "").strip()
    order_type = _normalize_pos_order_type(row["order_type"])
    inv_outlet = normalize_pos_outlet(row["outlet"] if "outlet" in row.keys() else None)
    if table_label and order_type == "dine_in":
        _pos_mark_table_occupied(conn, table_label, inv_outlet)

    return get_pos_invoice(conn, invoice_id)


def list_pos_kot_tokens(conn, outlet=POS_OUTLET_RESTAURANT):
    """Open dine-in bills that already have kitchen-sent qty — Tables KOT hub.

    Used to resend / reprint a token when kitchen missed the slip. Only lines with
    sent_qty > 0 are included (the last confirmed kitchen copy).
    Once the customer invoice is generated (customer_bill_sent), the token is
    removed from this list.
    """
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
    floor_by_name = {}
    for t in (layout or {}).get("tables") or []:
        key = str(t.get("name") or "").strip().lower()
        if key:
            floor_by_name[key] = t

    rows = conn.execute(
        """
        SELECT
            i.id AS invoice_id,
            i.order_no AS order_no,
            i.table_label AS name,
            i.order_type AS order_type,
            i.first_kot_at AS first_kot_at,
            i.saved_at AS saved_at,
            i.updated_at AS updated_at,
            COALESCE(i.customer_bill_sent, 0) AS customer_bill_sent,
            COALESCE(i.customer_bill_at, '') AS customer_bill_at,
            COALESCE(i.kot_no, '') AS kot_no,
            COUNT(l.id) AS sent_items,
            COALESCE(SUM(COALESCE(l.sent_qty, 0)), 0) AS sent_qty
        FROM pos_invoices i
        JOIN pos_invoice_lines l
          ON l.invoice_id = i.id
         AND COALESCE(l.sent_qty, 0) > 0
        WHERE i.is_active = 1
          AND i.status = 'open'
          AND i.order_type = 'dine_in'
          AND i.outlet = ?
          AND TRIM(COALESCE(i.table_label, '')) != ''
          AND COALESCE(i.customer_bill_sent, 0) = 0
          AND TRIM(COALESCE(i.customer_bill_at, '')) = ''
        GROUP BY
            i.id, i.order_no, i.table_label, i.order_type,
            i.first_kot_at, i.saved_at, i.updated_at,
            i.customer_bill_sent, i.customer_bill_at, i.kot_no
        ORDER BY i.table_label ASC, i.id ASC
        """,
        (outlet,),
    ).fetchall()

    tables = []
    for row in rows:
        name = (row["name"] or "").strip()
        floor = floor_by_name.get(name.lower()) or {}
        seats = floor.get("seats")
        try:
            seats = int(seats) if seats is not None and str(seats).strip() != "" else None
        except (TypeError, ValueError):
            seats = None
        table_status = str(floor.get("status") or "occupied").strip().lower() or "occupied"
        order_no = (row["order_no"] or "").strip()
        stored_kot = (row["kot_no"] or "").strip() if "kot_no" in row.keys() else ""
        invoice_id = int(row["invoice_id"])
        if not stored_kot and (row["first_kot_at"] or "").strip():
            stored_kot = ensure_pos_invoice_kot_no(conn, invoice_id, outlet=outlet)
        kot_no = pos_kot_display_no(order_no, stored_kot)
        sent_at = (row["first_kot_at"] or row["updated_at"] or row["saved_at"] or "").strip()
        line_rows = conn.execute(
            """
            SELECT
                l.id,
                l.name,
                l.variant,
                l.qty,
                COALESCE(l.sent_qty, 0) AS sent_qty,
                COALESCE(l.notes, '') AS notes,
                m.outlet AS menu_outlet
            FROM pos_invoice_lines l
            LEFT JOIN pos_menu_items m ON m.id = l.menu_item_id
            WHERE l.invoice_id = ?
              AND COALESCE(l.sent_qty, 0) > 0
            ORDER BY l.sort_order ASC, l.id ASC
            """,
            (invoice_id,),
        ).fetchall()
        lines = []
        for line in line_rows:
            sent_qty = float(line["sent_qty"] or 0)
            keys = line.keys()
            menu_outlet = "restaurant"
            if "menu_outlet" in keys:
                menu_outlet = normalize_pos_outlet(line["menu_outlet"])
            lines.append(
                {
                    "id": int(line["id"]),
                    "name": (line["name"] or "").strip(),
                    "variant": (line["variant"] or "").strip(),
                    "qty": sent_qty,
                    "sent_qty": sent_qty,
                    "notes": (line["notes"] or "").strip() if "notes" in keys else "",
                    "outlet": menu_outlet,
                }
            )
        tables.append(
            {
                "name": name,
                "invoice_id": invoice_id,
                "order_no": order_no,
                "kot_no": kot_no,
                "order_type": _normalize_pos_order_type(row["order_type"]),
                "sent_items": int(row["sent_items"] or 0),
                "sent_qty": int(float(row["sent_qty"] or 0)),
                "seats": seats,
                "table_status": table_status,
                "sent_at": sent_at,
                "customer_bill_sent": bool(row["customer_bill_sent"]),
                "customer_bill_at": (row["customer_bill_at"] or "").strip(),
                "lines": lines,
            }
        )
    return {
        "token_count": len(tables),
        "tables": tables,
    }


def apply_pos_kot_token_reductions(conn, changes, *, allow_kot_cancel=False, created_by="", reason="", outlet=None):
    """Adjust kitchen-sent quantities from the Tables KOT hub and sync the bill.

    ``changes`` is a list of {invoice_id, line_id, sent_qty} where sent_qty is the
    new kitchen-sent amount (0 removes that sent portion / line when qty hits 0;
    values above the previous sent qty increase both kitchen-sent and bill qty).
    Requires KOT Cancellation (allow_kot_cancel=True). A non-empty reason is required
    only when any line is reduced (or the order is fully cancelled).
    """
    ensure_pos_schema(conn)
    if not allow_kot_cancel:
        raise ValueError("KOT Cancellation is required to edit kitchen-sent items.")
    if not isinstance(changes, list) or not changes:
        raise ValueError("No quantity changes to save.")
    reason_text = " ".join(str(reason or "").split()).strip()
    if len(reason_text) > 500:
        reason_text = reason_text[:500]

    by_invoice = {}
    for raw in changes:
        if not isinstance(raw, dict):
            continue
        try:
            invoice_id = int(raw.get("invoice_id") or raw.get("invoiceId"))
            line_id = int(raw.get("line_id") or raw.get("lineId"))
        except (TypeError, ValueError):
            continue
        try:
            new_sent = float(raw.get("sent_qty", raw.get("sentQty")))
        except (TypeError, ValueError):
            continue
        if new_sent < 0:
            new_sent = 0.0
        by_invoice.setdefault(invoice_id, {})[line_id] = new_sent

    if not by_invoice:
        raise ValueError("No quantity changes to save.")

    if outlet is not None:
        wanted = normalize_pos_outlet(outlet)
        for invoice_id in list(by_invoice.keys()):
            invoice = get_pos_invoice(conn, invoice_id)
            if not invoice or normalize_pos_outlet(invoice.get("outlet")) != wanted:
                raise ValueError(f"Invoice #{invoice_id} not found.")

    # Detect reductions against current DB state so reason rules are accurate.
    has_reduction = False
    for invoice_id, line_map in by_invoice.items():
        invoice = get_pos_invoice(conn, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice #{invoice_id} not found.")
        for line in invoice.get("lines") or []:
            lid = int(line.get("id") or 0)
            if lid not in line_map:
                continue
            old_sent = _pos_money(line.get("sent_qty"))
            new_sent = _pos_money(line_map[lid])
            if new_sent + 1e-9 < old_sent:
                has_reduction = True
                break
        if has_reduction:
            break

    if has_reduction and not reason_text:
        raise ValueError("Enter a reason for reducing or cancelling kitchen items.")

    updated = []
    for invoice_id, line_map in by_invoice.items():
        invoice = get_pos_invoice(conn, invoice_id)
        if not invoice:
            raise ValueError(f"Invoice #{invoice_id} not found.")
        status_key = str(invoice.get("status") or "open").strip().lower() or "open"
        if status_key == "closed":
            raise ValueError("Settled invoices cannot be updated from Kitchen Order Tokens.")
        if status_key == "cancelled":
            raise ValueError("Cancelled invoices cannot be updated from Kitchen Order Tokens.")
        if status_key != "open":
            raise ValueError("Only open invoices can be updated from Kitchen Order Tokens.")

        bill_sent = bool(invoice.get("customer_bill_sent"))
        next_lines = []
        changed = False
        invoice_has_reduction = False
        for line in invoice.get("lines") or []:
            lid = int(line.get("id") or 0)
            old_sent = _pos_money(line.get("sent_qty"))
            old_qty = _pos_money(line.get("qty"))
            if lid not in line_map:
                next_lines.append(
                    {
                        "uid": line.get("uid") or line.get("line_uid"),
                        "menuId": line.get("menu_item_id"),
                        "name": line.get("name"),
                        "variant": line.get("variant") or "",
                        "rate": line.get("rate"),
                        "qty": old_qty,
                        "kotSentQty": old_sent,
                        "notes": line.get("notes") or "",
                    }
                )
                continue
            new_sent = _pos_money(line_map[lid])
            if abs(new_sent - old_sent) <= 1e-9:
                next_lines.append(
                    {
                        "uid": line.get("uid") or line.get("line_uid"),
                        "menuId": line.get("menu_item_id"),
                        "name": line.get("name"),
                        "variant": line.get("variant") or "",
                        "rate": line.get("rate"),
                        "qty": old_qty,
                        "kotSentQty": old_sent,
                        "notes": line.get("notes") or "",
                    }
                )
                continue
            if new_sent > old_sent:
                if bill_sent:
                    raise ValueError(
                        f'Invoice for {invoice.get("table") or "table"} is already generated.'
                    )
                delta = new_sent - old_sent
                new_qty = old_qty + delta
                changed = True
                next_lines.append(
                    {
                        "uid": line.get("uid") or line.get("line_uid"),
                        "menuId": line.get("menu_item_id"),
                        "name": line.get("name"),
                        "variant": line.get("variant") or "",
                        "rate": line.get("rate"),
                        "qty": new_qty,
                        "kotSentQty": new_sent,
                        "notes": line.get("notes") or "",
                    }
                )
                continue

            invoice_has_reduction = True
            delta = old_sent - new_sent
            new_qty = old_qty - delta
            if new_qty <= 1e-9:
                changed = True
                continue
            if bill_sent:
                # Generated bills: only a full cancel (all lines to zero) is allowed.
                raise ValueError(
                    f'Invoice for {invoice.get("table") or "table"} is already generated. '
                    "Cancel the whole order, or cancel the invoice from Invoice Ledger."
                )
            changed = True
            next_lines.append(
                {
                    "uid": line.get("uid") or line.get("line_uid"),
                    "menuId": line.get("menu_item_id"),
                    "name": line.get("name"),
                    "variant": line.get("variant") or "",
                    "rate": line.get("rate"),
                    "qty": new_qty,
                    "kotSentQty": new_sent,
                    "notes": line.get("notes") or "",
                }
            )

        if not changed:
            continue
        table_label = invoice.get("table") or invoice.get("table_label") or ""
        if not next_lines:
            # Full kitchen cancel — void via cancel_pos_invoice so generated /
            # official numbers stay as status=cancelled (KOT report) and drafts soft-delete.
            if not reason_text:
                raise ValueError("Enter a reason for reducing or cancelling kitchen items.")
            cancel_pos_invoice(
                conn,
                invoice_id,
                reason=reason_text,
                cancelled_by=created_by,
            )
            updated.append(
                {
                    "id": invoice_id,
                    "cancelled": True,
                    "table": table_label,
                    "table_label": table_label,
                    "outlet": invoice.get("outlet"),
                    "order_no": invoice.get("order_no"),
                    "cancel_reason": reason_text,
                    "cancelled_by": " ".join(str(created_by or "").split()).strip(),
                }
            )
            continue

        if bill_sent:
            raise ValueError(
                f'Invoice for {invoice.get("table") or "table"} is already generated.'
            )

        subtotal = _pos_money(sum(_pos_money(l["rate"]) * _pos_money(l["qty"]) for l in next_lines))
        # Preserve discount/service/tip structure; totals recomputed in save_pos_invoice.
        payload = {
            "orderNo": invoice.get("order_no"),
            "outlet": invoice.get("outlet"),
            "orderType": invoice.get("order_type"),
            "table": table_label,
            "captain": invoice.get("captain") or "",
            "customerName": invoice.get("customer_name") or "Guest",
            "customerMobile": invoice.get("customer_mobile") or "",
            "notes": invoice.get("notes") or "",
            "discountType": invoice.get("discount_type") or "pct",
            "discountValue": invoice.get("discount_value") or 0,
            "discountLineUids": invoice.get("discount_line_uids") or [],
            "discountReason": invoice.get("discount_reason") or "",
            "serviceType": invoice.get("service_type") or "pct",
            "serviceValue": invoice.get("service_value") or 0,
            "tipAmount": invoice.get("tip_amount") or 0,
            "couponCode": invoice.get("coupon_code") or "",
            "lines": next_lines,
            "totals": {
                "subtotal": subtotal,
                "discount": invoice.get("discount") or 0,
                "gst": invoice.get("gst") or 0,
                "vat": invoice.get("vat") or 0,
                "service": invoice.get("service") or 0,
                "tip": invoice.get("tip") or 0,
                "roundOff": invoice.get("round_off") or 0,
                "total": invoice.get("grand_total") or subtotal,
            },
        }
        saved = save_pos_invoice(
            conn,
            payload,
            created_by=created_by,
            allow_kot_cancel=True,
        )
        if invoice_has_reduction and reason_text:
            conn.execute(
                f"""
                UPDATE pos_invoices
                SET cancel_reason = ?,
                    updated_at = {SQL_NOW}
                WHERE id = ?
                """,
                (reason_text, invoice_id),
            )
            if isinstance(saved, dict):
                saved = dict(saved)
                saved["cancel_reason"] = reason_text
        updated.append(saved)

    if not updated:
        raise ValueError("No kitchen quantities were changed.")
    cancelled_count = sum(1 for inv in updated if inv.get("cancelled"))
    return {
        "updated_count": len(updated),
        "cancelled_count": cancelled_count,
        "invoices": updated,
    }


def close_pos_invoice_and_free_table(conn, invoice_id, *, user_id=None):
    """Close a bill (status -> 'closed') and free its table, if any. Decoupled
    from real payment for now — this is the 'Close & Free Table' action.

    On close, recipe ingredients for sold lines are deducted from store stock
    once (idempotent via stock_deducted_at / movement ref). Stock shortfalls
    never block closing the bill.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        "SELECT id, table_label, order_type, outlet FROM pos_invoices WHERE id = ? AND is_active = 1",
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    conn.execute(
        f"""
        UPDATE pos_invoices SET status = 'closed', updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (invoice_id,),
    )
    table_label = row["table_label"] or ""
    order_type = _normalize_pos_order_type(row["order_type"])
    inv_outlet = normalize_pos_outlet(row["outlet"] if "outlet" in row.keys() else None)
    if table_label and order_type == "dine_in":
        _pos_mark_table_available(conn, table_label, inv_outlet)
    try:
        from stores import deduct_stock_for_pos_invoice

        deduct_stock_for_pos_invoice(conn, invoice_id, user_id=user_id)
    except Exception:
        import logging

        logging.getLogger(__name__).exception(
            "POS stock deduction failed for invoice_id=%s (bill still closed)",
            invoice_id,
        )
    return get_pos_invoice(conn, invoice_id)


POS_PAYMENT_METHODS = (
    ("cash", "Cash"),
    ("upi", "UPI"),
    ("card", "Card"),
    ("room_transfer", "Room Transfer"),
    ("bank_transfer", "Bank Transfer"),
    ("swiggy", "Swiggy"),
    ("zomato", "Zomato"),
)
POS_PAYMENT_METHOD_LABELS = dict(POS_PAYMENT_METHODS)
# Kept for historical settlements that still show in Invoice Ledger.
POS_PAYMENT_METHOD_LABELS["credit"] = "Credit"
POS_PAYMENT_METHODS_REQUIRING_TXN = frozenset({"bank_transfer"})
POS_LEDGER_PAYMENT_AMOUNT_KEYS = tuple(key for key, _label in POS_PAYMENT_METHODS)


def _empty_pos_payment_amounts():
    """Zeroed tender map for ledger / KPI settlement columns."""
    return {key: 0.0 for key in POS_LEDGER_PAYMENT_AMOUNT_KEYS}


def _pos_payment_amounts_from_rows(rows):
    """Sum payment amounts by normalized method for ledger columns."""
    amounts = _empty_pos_payment_amounts()
    for row in rows or []:
        if isinstance(row, dict):
            method = row.get("payment_method") or row.get("method")
            amount = row.get("amount")
        else:
            try:
                method = row["payment_method"]
                amount = row["amount"]
            except (TypeError, KeyError, IndexError):
                continue
        key = _normalize_pos_payment_method(method)
        if not key or key not in amounts:
            continue
        amounts[key] = _pos_money(amounts[key] + _pos_money(amount))
    return amounts


def _normalize_pos_payment_method(payment_method):
    value = str(payment_method or "").strip().lower()
    if value in ("bank_transfer", "bank", "bank transfer"):
        return "bank_transfer"
    if value == "upi":
        return "upi"
    if value in ("card", "credit card", "debit card"):
        return "card"
    if value == "cash":
        return "cash"
    if value in ("room_transfer", "room transfer"):
        return "room_transfer"
    if value == "swiggy":
        return "swiggy"
    if value == "zomato":
        return "zomato"
    # Historical ledger rows only — not offered for new settlements.
    if value == "credit":
        return "credit"
    return None


def _parse_pos_payment_splits(raw_splits, target_total):
    """Validate payment_splits the same way Room Transfer Clear Payment does."""
    target = _pos_money(target_total)
    if target < 0:
        raise ValueError("Bill total cannot be negative.")
    if not isinstance(raw_splits, list) or not raw_splits:
        # Zero-payable bills need no tender — settle with an empty split list.
        if target <= 0:
            return []
        raise ValueError("Add at least one payment mode.")

    parsed = []
    seen = set()
    for raw in raw_splits:
        if not isinstance(raw, dict):
            raise ValueError("Each payment split must be an object.")
        method = _normalize_pos_payment_method(
            raw.get("payment_method") or raw.get("method")
        )
        allowed = {key for key, _label in POS_PAYMENT_METHODS}
        if not method or method not in allowed:
            raise ValueError("Select a valid payment mode for each row.")
        if method in seen:
            raise ValueError("Each payment mode can only be used once.")
        seen.add(method)
        amount = _pos_money(raw.get("amount"))
        if amount <= 0 and target > 0:
            raise ValueError("Enter a valid amount for each payment mode.")
        if amount < 0:
            raise ValueError("Payment amounts cannot be negative.")
        txn = str(raw.get("transaction_id") or "").strip()
        if method in POS_PAYMENT_METHODS_REQUIRING_TXN and not txn:
            raise ValueError("Transaction ID is required for bank transfer.")
        if method not in POS_PAYMENT_METHODS_REQUIRING_TXN:
            txn = ""
        parsed.append(
            {
                "payment_method": method,
                "amount": amount,
                "transaction_id": txn,
            }
        )

    split_total = _pos_money(sum(item["amount"] for item in parsed))
    if abs(split_total - target) > 0.001:
        raise ValueError("Modes total must equal the bill total before settling.")
    return parsed


def settle_pos_invoice(
    conn,
    invoice_id,
    *,
    payment_splits=None,
    payment_date=None,
    notes="",
    user_id=None,
    hotel_room_id=None,
):
    """Record payment (with optional split modes) and close the bill / free table.

    Mirrors Sales Analytics → Room Transfer → Clear Payment: modes must sum to
    the bill total; bank transfer requires a transaction id.

    When any split uses room_transfer, hotel_room_id must reference an occupied
    hotel room; the room-transfer amount is posted onto that stay's folio.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc

    row = conn.execute(
        """
        SELECT id, status, grand_total, settled_at, outlet, order_no
        FROM pos_invoices
        WHERE id = ? AND is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    if str(row["status"] or "").strip().lower() == "closed":
        raise ValueError("This bill is already settled.")

    target = _pos_money(row["grand_total"])
    splits = _parse_pos_payment_splits(payment_splits, target)
    room_transfer_total = round(
        sum(
            float(s["amount"])
            for s in splits
            if s.get("payment_method") == "room_transfer"
        ),
        2,
    )
    hotel_room_id = str(hotel_room_id or "").strip()
    if room_transfer_total > 0 and not hotel_room_id:
        raise ValueError("Select a hotel room for Room Transfer payment.")

    pay_date = str(payment_date or "").strip()
    if not pay_date:
        pay_date = conn.execute("SELECT date('now','localtime')").fetchone()[0]
    notes_clean = str(notes or "").strip()
    transfer_room_number = (
        _pos_room_number_for_hotel_room_id(conn, hotel_room_id)
        if room_transfer_total > 0
        else ""
    )

    # Replace any prior draft payments (should be empty for open bills).
    conn.execute("DELETE FROM pos_invoice_payments WHERE invoice_id = ?", (invoice_id,))
    for split in splits:
        pay_notes = notes_clean
        if split.get("payment_method") == "room_transfer" and transfer_room_number:
            pay_notes = _pos_payment_notes_with_room_number(
                notes_clean, transfer_room_number
            )
        conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_date, payment_method, amount, transaction_id, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                pay_date,
                split["payment_method"],
                split["amount"],
                split["transaction_id"],
                pay_notes,
            ),
        )

    conn.execute(
        f"""
        UPDATE pos_invoices
        SET payment_notes = ?, settled_at = {SQL_NOW}, updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (notes_clean, invoice_id),
    )

    invoice = close_pos_invoice_and_free_table(conn, invoice_id, user_id=user_id)
    payments = list_pos_invoice_payments(conn, invoice_id)
    invoice["payments"] = payments
    invoice["payment_notes"] = notes_clean

    if room_transfer_total > 0:
        outlet = str(row["outlet"] or (invoice or {}).get("outlet") or "")
        order_no = str(row["order_no"] or (invoice or {}).get("order_no") or "")
        kind = _hotel_folio_kind_for_outlet(outlet)
        label = {
            "restaurant_room_transfer": "Restaurant Room Transfer",
            "bar_room_transfer": "Bar Room Transfer",
            "other": "Room Transfer",
        }.get(kind, "Room Transfer")
        if order_no:
            label = f"{label} · {order_no}"
        folio_result = append_hotel_room_folio_charge(
            conn,
            hotel_room_id,
            amount=room_transfer_total,
            kind=kind,
            label=label,
            source="pos",
            invoice_id=str(invoice_id),
            order_no=order_no,
            outlet=outlet,
            note=notes_clean,
        )
        invoice["hotel_room"] = folio_result.get("room")
        invoice["folio_charge"] = folio_result.get("charge")
        room = folio_result.get("room")
        charge = folio_result.get("charge")
        if room and charge:
            # Persist per-POS transfer row so Invoice Ledger can show the room
            # number even after the stay folio is cleared. Combined FBE is still
            # minted later at Generate Invoice.
            upsert_pos_room_transfer_invoice(conn, room, charge)
        # Rebuild Payment Mode after folio post so Room Transfer includes room #.
        _apply_pos_invoice_payment_modes(conn, invoice)
    return invoice


def _allocate_pos_invoice_payment_splits(invoices, splits):
    """Assign payment splits across invoices in list order until the pool is empty."""
    pool = [dict(split) for split in splits or []]
    allocations = []
    for invoice in invoices or []:
        need = _pos_money(invoice.get("grand_total"))
        taken = []
        while need > 0.009 and pool:
            head = pool[0]
            avail = _pos_money(head.get("amount"))
            if avail <= 0.009:
                pool.pop(0)
                continue
            take = _pos_money(min(avail, need))
            piece = dict(head)
            piece["amount"] = take
            taken.append(piece)
            leftover = _pos_money(avail - take)
            need = _pos_money(need - take)
            if leftover <= 0.009:
                pool.pop(0)
            else:
                remaining = dict(head)
                remaining["amount"] = leftover
                pool[0] = remaining
        allocations.append((invoice, taken, need))
    leftover_total = _pos_money(sum(float(split.get("amount") or 0) for split in pool))
    return allocations, leftover_total


def settle_pos_invoices(
    conn,
    invoice_ids,
    *,
    payment_splits=None,
    payment_date=None,
    notes="",
    user_id=None,
    hotel_room_id=None,
):
    """Record one payment across multiple open POS invoices (FIFO)."""
    ensure_pos_schema(conn)
    ids = []
    seen = set()
    raw_list = invoice_ids if isinstance(invoice_ids, (list, tuple)) else []
    for raw in raw_list:
        try:
            iid = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid invoice id.") from exc
        if iid in seen:
            raise ValueError("The same invoice was selected more than once.")
        seen.add(iid)
        ids.append(iid)
    if not ids:
        raise ValueError("Select at least one invoice.")

    invoices = []
    combined = 0.0
    for iid in ids:
        invoice = get_pos_invoice(conn, iid)
        if not invoice:
            raise ValueError("Invoice not found.")
        status = str(invoice.get("status") or "").strip().lower() or "open"
        order_no = str(invoice.get("order_no") or iid)
        if status == "cancelled":
            raise ValueError(f"Invoice {order_no} is cancelled.")
        if status == "closed" or str(invoice.get("settled_at") or "").strip():
            raise ValueError(f"Invoice {order_no} is already settled.")
        invoices.append(invoice)
        combined = _pos_money(combined + _pos_money(invoice.get("grand_total")))

    splits = _parse_pos_payment_splits(payment_splits, combined)
    allocations, leftover = _allocate_pos_invoice_payment_splits(invoices, splits)
    if leftover > 0.009:
        raise ValueError("Modes total must equal the bill total before settling.")
    for invoice, taken, remaining in allocations:
        if remaining > 0.009:
            raise ValueError("Modes total must equal the bill total before settling.")
        if _pos_money(invoice.get("grand_total")) > 0.009 and not taken:
            raise ValueError("Enter a payment amount.")

    results = []
    for invoice, taken, _remaining in allocations:
        results.append(
            settle_pos_invoice(
                conn,
                invoice.get("id"),
                payment_splits=taken,
                payment_date=payment_date,
                notes=notes,
                user_id=user_id,
                hotel_room_id=hotel_room_id,
            )
        )
    return {
        "invoices": results,
        "invoice": results[0] if len(results) == 1 else None,
        "settled_count": sum(
            1
            for inv in results
            if inv and str(inv.get("status") or "").strip().lower() == "closed"
        ),
        "paid_count": len(results),
    }


def import_settled_pos_invoice_snapshot(conn, snapshot):
    """Upsert a historical settled POS invoice (no table occupancy / stock / folio).

    ``snapshot`` keys:
      order_no, outlet, order_type, order_date, saved_at, settled_at, customer_name,
      notes, subtotal, discount_amount, gst_amount, vat_amount, grand_total,
      lines: [{name, rate, qty, line_total, menu_item_id?}],
      payments: [{payment_method, amount, payment_date, transaction_id?, notes?}]
    """
    ensure_pos_schema(conn)
    if not isinstance(snapshot, dict):
        raise ValueError("Invalid invoice snapshot.")
    order_no = " ".join(str(snapshot.get("order_no") or "").split()).strip()
    if not order_no:
        raise ValueError("Order number is required.")
    outlet = normalize_pos_outlet(snapshot.get("outlet"))
    order_type = _normalize_pos_order_type(snapshot.get("order_type") or "dine_in")
    customer_name = " ".join(
        str(snapshot.get("customer_name") or "Guest").split()
    ).strip() or "Guest"
    order_date = str(snapshot.get("order_date") or "").strip()[:10]
    if not order_date:
        raise ValueError("Order date is required.")
    saved_at = str(snapshot.get("saved_at") or "").strip()
    if not saved_at:
        saved_at = f"{order_date} 12:00:00"
    settled_at = str(snapshot.get("settled_at") or saved_at).strip()
    notes = str(snapshot.get("notes") or "").strip()[:500]
    payment_notes = str(snapshot.get("payment_notes") or "Imported from sales ledger").strip()[
        :500
    ]

    subtotal = _pos_money(snapshot.get("subtotal"))
    discount_amount = _pos_money(snapshot.get("discount_amount"))
    gst_amount = _pos_money(snapshot.get("gst_amount"))
    vat_amount = _pos_money(snapshot.get("vat_amount"))
    grand_total = _pos_money(snapshot.get("grand_total"))
    if grand_total < 0:
        raise ValueError("Grand total cannot be negative.")

    lines_in = snapshot.get("lines") if isinstance(snapshot.get("lines"), list) else []
    lines = []
    for idx, line in enumerate(lines_in):
        if not isinstance(line, dict):
            continue
        name = " ".join(str(line.get("name") or "").split()).strip()
        if not name:
            continue
        qty = _pos_money(line.get("qty") if line.get("qty") is not None else 1) or 1.0
        rate = _pos_money(line.get("rate"))
        line_total = _pos_money(line.get("line_total"))
        if line_total <= 0 and rate > 0:
            line_total = round(rate * qty, 2)
        if line_total <= 0 and rate <= 0:
            continue
        menu_item_id = line.get("menu_item_id")
        try:
            menu_item_id = int(menu_item_id) if menu_item_id not in (None, "", 0, "0") else None
        except (TypeError, ValueError):
            menu_item_id = None
        if menu_item_id is not None and menu_item_id <= 0:
            menu_item_id = None
        lines.append(
            {
                "sort_order": idx,
                "menu_item_id": menu_item_id,
                "name": name[:200],
                "rate": rate if rate > 0 else line_total,
                "qty": qty,
                "line_total": line_total,
            }
        )
    if not lines:
        # Guarantee at least one line so ledger item counts stay honest.
        lines.append(
            {
                "sort_order": 0,
                "name": "Imported sale",
                "rate": grand_total,
                "qty": 1.0,
                "line_total": grand_total,
            }
        )
        if subtotal <= 0:
            subtotal = grand_total

    payments_in = snapshot.get("payments") if isinstance(snapshot.get("payments"), list) else []
    payments = []
    for raw in payments_in:
        if not isinstance(raw, dict):
            continue
        method = _normalize_pos_payment_method(raw.get("payment_method"))
        if not method:
            method = str(raw.get("payment_method") or "").strip().lower() or "cash"
        amount = _pos_money(raw.get("amount"))
        if amount <= 0:
            continue
        pay_date = str(raw.get("payment_date") or order_date).strip()[:10] or order_date
        payments.append(
            {
                "payment_method": method,
                "amount": amount,
                "payment_date": pay_date,
                "transaction_id": str(raw.get("transaction_id") or "").strip()[:80],
                "notes": str(raw.get("notes") or payment_notes).strip()[:200],
            }
        )
    if not payments and grand_total > 0:
        payments.append(
            {
                "payment_method": "cash",
                "amount": grand_total,
                "payment_date": order_date,
                "transaction_id": "",
                "notes": payment_notes,
            }
        )
    elif not payments:
        payments.append(
            {
                "payment_method": "cash",
                "amount": 0.0,
                "payment_date": order_date,
                "transaction_id": "",
                "notes": payment_notes,
            }
        )

    existing = conn.execute(
        """
        SELECT id FROM pos_invoices
        WHERE order_no = ? AND is_active = 1
        LIMIT 1
        """,
        (order_no,),
    ).fetchone()
    created = existing is None
    if existing:
        invoice_id = int(existing["id"])
        conn.execute(
            f"""
            UPDATE pos_invoices
            SET saved_at = ?,
                order_date = ?,
                order_type = ?,
                table_label = '',
                captain = '',
                customer_name = ?,
                customer_mobile = '',
                notes = ?,
                discount_type = 'inr',
                discount_value = ?,
                service_type = 'pct',
                service_value = 0,
                tip_amount = 0,
                coupon_code = '',
                discount_line_uids = '',
                discount_reason = '',
                subtotal = ?,
                discount_amount = ?,
                gst_amount = ?,
                vat_amount = ?,
                service_amount = 0,
                tip = 0,
                round_off = 0,
                grand_total = ?,
                status = 'closed',
                kot_sent = 0,
                first_kot_at = '',
                customer_bill_sent = 1,
                customer_bill_at = ?,
                payment_notes = ?,
                settled_at = ?,
                outlet = ?,
                stock_deducted_at = COALESCE(NULLIF(stock_deducted_at, ''), 'import-skip'),
                updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (
                saved_at,
                order_date,
                order_type,
                customer_name,
                notes,
                discount_amount,
                subtotal,
                discount_amount,
                gst_amount,
                vat_amount,
                grand_total,
                settled_at,
                payment_notes,
                settled_at,
                outlet,
                invoice_id,
            ),
        )
        conn.execute("DELETE FROM pos_invoice_lines WHERE invoice_id = ?", (invoice_id,))
        conn.execute("DELETE FROM pos_invoice_payments WHERE invoice_id = ?", (invoice_id,))
    else:
        cursor = conn.execute(
            f"""
            INSERT INTO pos_invoices (
                order_no, saved_at, order_date, order_type, table_label, captain,
                customer_name, customer_mobile, notes,
                discount_type, discount_value, service_type, service_value,
                tip_amount, coupon_code, discount_line_uids, discount_reason,
                subtotal, discount_amount, gst_amount, vat_amount, service_amount, tip,
                round_off, grand_total, created_by, status, kot_sent, first_kot_at,
                customer_bill_sent, customer_bill_at, payment_notes, settled_at,
                outlet, stock_deducted_at, is_active, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, '', '',
                ?, '', ?,
                'inr', ?, 'pct', 0,
                0, '', '', '',
                ?, ?, ?, ?, 0, 0,
                0, ?, 'sales_import', 'closed', 0, '',
                1, ?, ?, ?,
                ?, 'import-skip', 1, {SQL_NOW}, {SQL_NOW}
            )
            """,
            (
                order_no,
                saved_at,
                order_date,
                order_type,
                customer_name,
                notes,
                discount_amount,
                subtotal,
                discount_amount,
                gst_amount,
                vat_amount,
                grand_total,
                settled_at,
                payment_notes,
                settled_at,
                outlet,
            ),
        )
        invoice_id = int(cursor.lastrowid)

    for line in lines:
        conn.execute(
            """
            INSERT INTO pos_invoice_lines (
                invoice_id, sort_order, menu_item_id, name, variant, rate, qty,
                line_total, sent_qty, notes, line_uid
            ) VALUES (?, ?, ?, ?, '', ?, ?, ?, 0, 'import', ?)
            """,
            (
                invoice_id,
                line["sort_order"],
                line.get("menu_item_id"),
                line["name"],
                line["rate"],
                line["qty"],
                line["line_total"],
                f"imp-{line['sort_order']}",
            ),
        )
    for pay in payments:
        conn.execute(
            """
            INSERT INTO pos_invoice_payments
                (invoice_id, payment_date, payment_method, amount, transaction_id, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                pay["payment_date"],
                pay["payment_method"],
                pay["amount"],
                pay["transaction_id"],
                pay["notes"],
            ),
        )
    return {
        "id": invoice_id,
        "order_no": order_no,
        "outlet": outlet,
        "created": created,
        "status": "closed",
        "grand_total": grand_total,
    }


def list_pos_invoice_payments(conn, invoice_id):
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError):
        return []
    rows = conn.execute(
        """
        SELECT id, payment_date, payment_method, amount, transaction_id, notes, created_at
        FROM pos_invoice_payments
        WHERE invoice_id = ?
        ORDER BY id ASC
        """,
        (invoice_id,),
    ).fetchall()
    out = []
    for row in rows:
        method = row["payment_method"] or "cash"
        out.append(
            {
                "id": row["id"],
                "payment_date": row["payment_date"] or "",
                "payment_method": method,
                "payment_method_label": POS_PAYMENT_METHOD_LABELS.get(method, method),
                "amount": _pos_money(row["amount"]),
                "transaction_id": row["transaction_id"] or "",
                "notes": row["notes"] or "",
                "created_at": row["created_at"] or "",
            }
        )
    return out


def clear_all_pos_tables(conn, *, user_id=None, outlet=POS_OUTLET_RESTAURANT):
    """Bulk-free every table on the floor back to available (Tables page 'Clear
    all tables'). Also closes any dangling open dine-in bills tied to those
    tables so a later resume lookup can't resurrect a stale order."""
    ensure_pos_schema(conn)
    outlet = normalize_pos_outlet(outlet)
    layout = get_pos_floor_layout(conn, outlet)
    tables = layout.get("tables") or []
    closed_ids = []
    for t in tables:
        label = str(t.get("name") or "").strip()
        if label:
            open_rows = conn.execute(
                """
                SELECT id FROM pos_invoices
                WHERE is_active = 1 AND status = 'open' AND order_type = 'dine_in'
                  AND outlet = ?
                  AND LOWER(table_label) = LOWER(?)
                """,
                (outlet, label),
            ).fetchall()
            for open_row in open_rows:
                closed_ids.append(int(open_row["id"]))
            conn.execute(
                f"""
                UPDATE pos_invoices SET status = 'closed', updated_at = {SQL_NOW}
                WHERE is_active = 1 AND status = 'open' AND order_type = 'dine_in'
                  AND outlet = ?
                  AND LOWER(table_label) = LOWER(?)
                """,
                (outlet, label),
            )
        t["status"] = "available"
        t["mergeGroupId"] = None
        t["mergePrimary"] = False
    if closed_ids:
        try:
            from stores import deduct_stock_for_pos_invoice

            for inv_id in closed_ids:
                try:
                    deduct_stock_for_pos_invoice(conn, inv_id, user_id=user_id)
                except Exception:
                    import logging

                    logging.getLogger(__name__).exception(
                        "POS stock deduction failed for invoice_id=%s during clear-all",
                        inv_id,
                    )
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "POS stock deduction unavailable during clear-all"
            )
    return save_pos_floor_layout(conn, layout.get("areas") or [], tables, outlet)


def _pos_invoice_line_kitchen_key(menu_item_id, name, variant):
    return (
        str(menu_item_id if menu_item_id is not None else ""),
        str(name or "").strip().lower(),
        str(variant or "").strip().lower(),
    )


def _enforce_pos_kot_line_protections(
    conn,
    invoice_id,
    normalized_lines,
    *,
    allow_kot_cancel=False,
    customer_bill_sent=False,
):
    """Protect kitchen-sent quantities unless Cancellation (KOT Edit) is granted.

    Reduce/remove of kitchen-sent amounts must go through Tables → Kitchen Order
    Tokens (Edit) with a reason (allow_kot_cancel=True). Create Invoice may still
    increase qty or trim only unsent units. After Generate Invoice the same floor
    applies; cancel rights are still required to go below prior sent_qty.
    """
    if not invoice_id:
        return
    if allow_kot_cancel:
        return
    old_rows = conn.execute(
        """
        SELECT menu_item_id, name, variant, qty, COALESCE(sent_qty, 0) AS sent_qty
        FROM pos_invoice_lines
        WHERE invoice_id = ?
          AND COALESCE(sent_qty, 0) > 0
        """,
        (invoice_id,),
    ).fetchall()
    if not old_rows:
        return

    required = {}
    for row in old_rows:
        key = _pos_invoice_line_kitchen_key(row["menu_item_id"], row["name"], row["variant"])
        required[key] = required.get(key, 0.0) + float(row["sent_qty"] or 0)

    available = {}
    for line in normalized_lines:
        key = _pos_invoice_line_kitchen_key(line.get("menu_item_id"), line.get("name"), line.get("variant"))
        available[key] = available.get(key, 0.0) + float(line.get("qty") or 0)

    for key, need in required.items():
        have = available.get(key, 0.0)
        if have + 1e-9 < need:
            raise ValueError(
                "Kitchen-sent items cannot be reduced or removed here. "
                "Use Tables → Kitchen Order Tokens (Edit) and enter a reason."
            )

    # Preserve kitchen-sent amounts on matching lines (ignore client zeroing).
    remaining = dict(required)
    for line in normalized_lines:
        key = _pos_invoice_line_kitchen_key(
            line.get("menu_item_id"), line.get("name"), line.get("variant")
        )
        need = remaining.get(key, 0.0)
        if need <= 0:
            continue
        qty = float(line.get("qty") or 0)
        take = min(qty, need)
        line["sent_qty"] = _pos_money(take)
        remaining[key] = need - take


def save_pos_invoice(conn, payload, *, created_by="", allow_kot_cancel=False, actor_is_admin=False):
    """Create or update a POS invoice by order_no. Returns the saved invoice dict.

    Kitchen-sent line reductions/removals require allow_kot_cancel (KOT Cancellation /
    Tables KOT Edit). Create Invoice may increase qty or change unsent units only.
    After Generate Invoice, normal saves are blocked once the invoice is generated.
    Banquet-only CGST/UGST percent overrides are stored only when actor_is_admin.
    """
    ensure_pos_schema(conn)
    if not isinstance(payload, dict):
        raise ValueError("Invalid invoice payload.")

    outlet = normalize_pos_outlet(payload.get("outlet") or payload.get("posOutlet"))
    order_no = " ".join(str(payload.get("orderNo") or payload.get("order_no") or "").split()).strip()
    if not order_no and outlet not in (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR):
        raise ValueError("Order number is required.")

    customer_name = " ".join(
        str(payload.get("customerName") or payload.get("customer_name") or "").split()
    ).strip()
    if not customer_name:
        raise ValueError("Customer name is required.")

    raw_lines = payload.get("lines")
    if not isinstance(raw_lines, list) or not raw_lines:
        raise ValueError("Add at least one item before saving.")

    totals = payload.get("totals") if isinstance(payload.get("totals"), dict) else {}
    order_type = _normalize_pos_order_type(payload.get("orderType") or payload.get("order_type"))
    saved_at = str(payload.get("savedAt") or payload.get("saved_at") or "").strip()
    if not saved_at:
        saved_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    order_date = str(payload.get("orderDate") or payload.get("order_date") or "").strip()
    if not order_date:
        # ISO or local datetime → date portion
        order_date = saved_at[:10] if len(saved_at) >= 10 else datetime.now().strftime("%Y-%m-%d")
    if "T" in order_date:
        order_date = order_date.split("T", 1)[0]

    # Restaurant/Bar keep provisional PREFIX/{hex}/{yy-yy} through Save/KOT.
    # Official PREFIX/{yy-yy}/{n} is minted only on Generate Invoice (below).
    if outlet in (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR) and not order_no:
        order_no = mint_provisional_pos_order_no(outlet, order_date, conn=conn)

    customer_mobile = "".join(
        ch for ch in str(payload.get("customerMobile") or payload.get("customer_mobile") or "") if ch.isdigit()
    )[:10]
    table_label = str(payload.get("table") or payload.get("table_label") or "").strip()
    captain = str(payload.get("captain") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    # Keep Customer Master in sync with POS Customer Details (unique 10-digit mobile).
    # Shared by Save, Send to Kitchen, Send to Customer, and any autosave that posts
    # to the same invoice API — incomplete mobiles are intentionally skipped.
    if len(customer_mobile) == 10:
        upsert_customer(conn, customer_name, customer_mobile)
    discount_type = str(
        payload.get("discountType") or totals.get("discountType") or "pct"
    ).strip().lower() or "pct"
    if discount_type not in ("pct", "inr"):
        discount_type = "pct"
    service_type = str(
        payload.get("serviceType") or totals.get("serviceType") or "pct"
    ).strip().lower() or "pct"
    if service_type not in ("pct", "inr"):
        service_type = "pct"
    discount_value = _pos_money(payload.get("discountValue", totals.get("discountValue")))
    service_value = _pos_money(payload.get("serviceValue", totals.get("serviceValue")))
    tip_amount = _pos_money(payload.get("tipAmount", totals.get("tip")))
    coupon_code = str(payload.get("couponCode") or payload.get("coupon_code") or "").strip()
    raw_discount_uids = payload.get("discountLineUids")
    if raw_discount_uids is None:
        raw_discount_uids = payload.get("discount_line_uids")
    if isinstance(raw_discount_uids, str):
        discount_line_uids = _parse_discount_line_uids(raw_discount_uids)
    elif isinstance(raw_discount_uids, (list, tuple)):
        discount_line_uids = _parse_discount_line_uids(json.dumps(list(raw_discount_uids)))
    else:
        discount_line_uids = []
    discount_reason = str(
        payload.get("discountReason") or payload.get("discount_reason") or ""
    ).strip()[:200]

    subtotal = _pos_money(totals.get("subtotal"))
    discount_amount = _pos_money(totals.get("discount"))
    gst_amount = _pos_money(totals.get("gst"))
    vat_amount = _pos_money(totals.get("vat"))
    service_amount = _pos_money(totals.get("service"))
    tip = _pos_money(totals.get("tip", tip_amount))
    round_off = _pos_money(totals.get("roundOff") or totals.get("round_off"))
    grand_total = _pos_money(totals.get("total") or totals.get("grand_total"))

    normalized_lines = []
    computed_subtotal = 0.0
    for idx, line in enumerate(raw_lines):
        if not isinstance(line, dict):
            continue
        name = " ".join(str(line.get("name") or "").split()).strip()
        if not name:
            continue
        rate = _pos_money(line.get("rate"))
        qty = _pos_money(line.get("qty"))
        if qty <= 0:
            continue
        line_total = _pos_money(rate * qty)
        computed_subtotal += line_total
        menu_item_id = line.get("menuId") if "menuId" in line else line.get("menu_item_id")
        try:
            menu_item_id = int(menu_item_id) if menu_item_id not in (None, "") else None
        except (TypeError, ValueError):
            menu_item_id = None
        sent_qty = _pos_money(line.get("kotSentQty", line.get("sent_qty")))
        if sent_qty < 0:
            sent_qty = 0.0
        if sent_qty > qty:
            sent_qty = qty
        line_notes = " ".join(str(line.get("notes") or "").split()).strip()[:200]
        line_uid = str(line.get("uid") or line.get("line_uid") or "").strip()
        if not line_uid:
            line_uid = f"L{idx + 1}"
        normalized_lines.append(
            {
                "sort_order": idx,
                "menu_item_id": menu_item_id,
                "name": name,
                "variant": str(line.get("variant") or "").strip(),
                "rate": rate,
                "qty": qty,
                "line_total": line_total,
                "sent_qty": sent_qty,
                "notes": line_notes,
                "line_uid": line_uid,
            }
        )
    if not normalized_lines:
        raise ValueError("Add at least one item before saving.")
    if subtotal <= 0:
        subtotal = _pos_money(computed_subtotal)

    # Keep only uids that still exist on this save; empty = whole-bill discount.
    live_uids = {line["line_uid"] for line in normalized_lines}
    discount_line_uids = [uid for uid in discount_line_uids if uid in live_uids]
    # Selecting every line is equivalent to whole-bill scope.
    if discount_line_uids and len(discount_line_uids) >= len(normalized_lines):
        discount_line_uids = []
    discount_line_uids_json = _serialize_discount_line_uids(discount_line_uids)
    if discount_amount <= 0 or discount_value <= 0:
        discount_reason = ""
    elif discount_type == "pct" and discount_value <= 15:
        discount_reason = ""
    elif discount_type == "inr" and subtotal > 0:
        effective_pct = (discount_amount / subtotal) * 100.0
        if effective_pct <= 15:
            discount_reason = ""

    banquet_only = _pos_lines_are_banquet_only(normalized_lines)
    posted_cgst_pct = _parse_pos_tax_override_pct(
        payload.get("taxCgstPct", payload.get("tax_cgst_pct"))
    )
    posted_ugst_pct = _parse_pos_tax_override_pct(
        payload.get("taxUgstPct", payload.get("tax_ugst_pct"))
    )

    # A KOT send persists the order and marks lines as sent to the kitchen.
    # Occupancy is claimed on any dine-in save with a table (see below).
    kot_send = bool(payload.get("kotSend") or payload.get("kot_send"))

    _existing_cols = """
        id, order_no, kot_sent, first_kot_at, kot_no, customer_bill_sent, customer_bill_at, outlet,
        table_label, tax_cgst_pct, tax_ugst_pct, status
    """
    existing = None
    if order_no:
        existing = conn.execute(
            f"""
            SELECT {_existing_cols}
            FROM pos_invoices
            WHERE order_no = ? AND is_active = 1
            LIMIT 1
            """,
            (order_no,),
        ).fetchone()
    if not existing:
        invoice_id_hint = payload.get("invoiceId")
        if invoice_id_hint is None:
            invoice_id_hint = payload.get("invoice_id")
        try:
            invoice_id_hint = int(invoice_id_hint) if invoice_id_hint is not None else None
        except (TypeError, ValueError):
            invoice_id_hint = None
        if invoice_id_hint:
            existing = conn.execute(
                f"""
                SELECT {_existing_cols}
                FROM pos_invoices
                WHERE id = ? AND is_active = 1
                LIMIT 1
                """,
                (invoice_id_hint,),
            ).fetchone()
            if existing and not order_no:
                order_no = str(existing["order_no"] or "").strip()
    if order_type != "dine_in":
        if existing:
            old_table = str(existing["table_label"] or "").strip()
            if old_table:
                was_bill_sent_existing = bool(existing["customer_bill_sent"]) if existing else False
                if not was_bill_sent_existing:
                    _pos_mark_table_available(conn, old_table, outlet)
        table_label = ""
    if existing:
        existing_status = str(existing["status"] or "open").strip().lower() or "open"
        if existing_status == "cancelled":
            raise ValueError(
                f'Invoice {order_no} was cancelled. Start a new order — cancelled numbers cannot be reused.'
            )
    if order_type == "dine_in" and not table_label and existing:
        table_label = str(existing["table_label"] or "").strip()
    if order_type == "dine_in" and not table_label:
        raise ValueError("Select a table before saving a dine-in order.")
    was_ever_generated = bool(
        str((existing["customer_bill_at"] if existing else "") or "").strip()
    )
    if existing:
        existing_outlet = normalize_pos_outlet(
            existing["outlet"] if "outlet" in existing.keys() else None
        )
        # Never rewrite a Restaurant bill from Bar (or vice versa) — order numbers
        # are globally unique, so a mismatched outlet is a conflict, not an update.
        if existing_outlet != outlet:
            raise ValueError(
                f'Order "{order_no}" already exists for {existing_outlet}. '
                "Use a new order number or open that outlet's POS."
            )
        outlet = existing_outlet

    if not banquet_only:
        tax_cgst_pct = None
        tax_ugst_pct = None
    elif actor_is_admin:
        tax_cgst_pct = posted_cgst_pct
        tax_ugst_pct = posted_ugst_pct
    elif existing:
        tax_cgst_pct = _row_tax_override_pct(existing, "tax_cgst_pct")
        tax_ugst_pct = _row_tax_override_pct(existing, "tax_ugst_pct")
    else:
        tax_cgst_pct = None
        tax_ugst_pct = None

    # A brand-new dine-in bill must not be openable against a table the Tables
    # page already shows as occupied — same floor/tables source of truth used
    # there. Editing an already-saved order (existing order_no) is a resume of
    # that same bill, so it is never blocked here.
    if not existing and table_label and order_type == "dine_in":
        floor_status = _pos_floor_table_status(get_pos_floor_layout(conn, outlet), table_label)
        if floor_status == "occupied":
            raise ValueError(
                f'Table "{table_label}" is occupied. Free it on the Tables page or choose another table.'
            )

    was_kot_sent = bool(existing["kot_sent"]) if existing else False
    next_kot_sent = 1 if (kot_send or was_kot_sent) else 0
    first_kot_at = (existing["first_kot_at"] if existing else "") or ""
    existing_kot_no = ""
    if existing and "kot_no" in existing.keys():
        existing_kot_no = str(existing["kot_no"] or "").strip()
    is_first_kot_send = bool(kot_send and not first_kot_at)
    if is_first_kot_send:
        first_kot_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    customer_bill = bool(payload.get("customerBill") or payload.get("customer_bill"))
    was_bill_sent = bool(existing["customer_bill_sent"]) if existing else False
    if was_bill_sent and not (customer_bill and was_ever_generated):
        raise ValueError("Invoice already generated; settle the bill instead.")
    next_bill_sent = 1 if (customer_bill or was_bill_sent) else 0
    customer_bill_at = (existing["customer_bill_at"] if existing else "") or ""
    if customer_bill and not customer_bill_at:
        customer_bill_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Official series only when Generate Invoice runs; lookup already used the
    # provisional order_no so the same row is updated with the new number.
    # Zero CGST+UGST and VAT uses PREFIX/{yy-yy}/Nill/{n}; otherwise PREFIX/{yy-yy}/{n}.
    # Also remint when Prefix settings changed (e.g. SPC/26-27 → SPC/27-28) and this
    # bill has not been generated yet — otherwise an already-official old-series
    # draft number would stick forever.
    if outlet in (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR) and customer_bill:
        nil_tax = pos_invoice_is_nil_tax(gst_amount, vat_amount)
        needs_mint = (not order_no) or is_provisional_pos_order_no(order_no, outlet)
        if not needs_mint and not was_bill_sent:
            stem, embedded_fy, _floor = pos_invoice_prefix_parts(conn, outlet)
            if nil_tax:
                series_re, _g1, _g2 = _pos_invoice_nill_order_re(stem, embedded_fy)
            else:
                series_re, _g1, _g2 = _pos_invoice_fy_order_re(stem, embedded_fy)
            needs_mint = not bool(series_re.match(str(order_no or "").strip()))
        if needs_mint:
            if outlet == POS_OUTLET_BAR:
                order_no = allocate_pos_bar_order_no(conn, order_date, nil_tax=nil_tax)
            else:
                order_no = allocate_pos_restaurant_order_no(conn, order_date, nil_tax=nil_tax)

    if _pos_order_no_taken(
        conn,
        order_no,
        outlet=outlet,
        ignore_invoice_id=int(existing["id"]) if existing else None,
    ):
        raise ValueError(
            f'Order number {order_no} is already reserved. Start a new order with a fresh draft.'
        )

    if existing:
        _enforce_pos_kot_line_protections(
            conn,
            int(existing["id"]),
            normalized_lines,
            allow_kot_cancel=bool(allow_kot_cancel),
            customer_bill_sent=bool(was_bill_sent),
        )

    creator = str(created_by or "").strip()
    if existing:
        invoice_id = int(existing["id"])
        conn.execute(
            f"""
            UPDATE pos_invoices SET
                order_no = ?,
                saved_at = ?,
                order_date = ?,
                order_type = ?,
                table_label = ?,
                captain = ?,
                customer_name = ?,
                customer_mobile = ?,
                notes = ?,
                discount_type = ?,
                discount_value = ?,
                service_type = ?,
                service_value = ?,
                tip_amount = ?,
                coupon_code = ?,
                discount_line_uids = ?,
                discount_reason = ?,
                subtotal = ?,
                discount_amount = ?,
                gst_amount = ?,
                vat_amount = ?,
                service_amount = ?,
                tip = ?,
                round_off = ?,
                grand_total = ?,
                tax_cgst_pct = ?,
                tax_ugst_pct = ?,
                kot_sent = ?,
                first_kot_at = ?,
                customer_bill_sent = ?,
                customer_bill_at = ?,
                updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (
                order_no,
                saved_at,
                order_date,
                order_type,
                table_label,
                captain,
                customer_name,
                customer_mobile,
                notes,
                discount_type,
                discount_value,
                service_type,
                service_value,
                tip_amount,
                coupon_code,
                discount_line_uids_json,
                discount_reason,
                subtotal,
                discount_amount,
                gst_amount,
                vat_amount,
                service_amount,
                tip,
                round_off,
                grand_total,
                tax_cgst_pct,
                tax_ugst_pct,
                next_kot_sent,
                first_kot_at,
                next_bill_sent,
                customer_bill_at,
                invoice_id,
            ),
        )
        conn.execute("DELETE FROM pos_invoice_lines WHERE invoice_id = ?", (invoice_id,))
    else:
        cursor = conn.execute(
            f"""
            INSERT INTO pos_invoices (
                order_no, saved_at, order_date, order_type, table_label, captain,
                customer_name, customer_mobile, notes,
                discount_type, discount_value, service_type, service_value,
                tip_amount, coupon_code, discount_line_uids, discount_reason,
                subtotal, discount_amount, gst_amount, vat_amount, service_amount, tip,
                round_off, grand_total, tax_cgst_pct, tax_ugst_pct, created_by, status, kot_sent, first_kot_at,
                customer_bill_sent, customer_bill_at, outlet,
                is_active, created_at, updated_at
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, 'open', ?, ?,
                ?, ?, ?,
                1, {SQL_NOW}, {SQL_NOW}
            )
            """,
            (
                order_no,
                saved_at,
                order_date,
                order_type,
                table_label,
                captain,
                customer_name,
                customer_mobile,
                notes,
                discount_type,
                discount_value,
                service_type,
                service_value,
                tip_amount,
                coupon_code,
                discount_line_uids_json,
                discount_reason,
                subtotal,
                discount_amount,
                gst_amount,
                vat_amount,
                service_amount,
                tip,
                round_off,
                grand_total,
                tax_cgst_pct,
                tax_ugst_pct,
                creator,
                next_kot_sent,
                first_kot_at,
                next_bill_sent,
                customer_bill_at,
                outlet,
            ),
        )
        invoice_id = int(cursor.lastrowid)

    for line in normalized_lines:
        conn.execute(
            """
            INSERT INTO pos_invoice_lines (
                invoice_id, sort_order, menu_item_id, name, variant, rate, qty, line_total, sent_qty, notes, line_uid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                invoice_id,
                line["sort_order"],
                line["menu_item_id"],
                line["name"],
                line["variant"],
                line["rate"],
                line["qty"],
                line["line_total"],
                line["sent_qty"],
                line.get("notes") or "",
                line.get("line_uid") or "",
            ),
        )

    # Claim the table while the dine-in bill is in progress. Generate Invoice
    # (customer_bill_sent) frees it immediately so the next party can sit —
    # Settle Bill can finish without holding the floor tile. Ledger modify
    # sessions keep customer_bill_at set — they must never reclaim the tile.
    if table_label and order_type == "dine_in":
        if next_bill_sent:
            _pos_mark_table_available(conn, table_label, outlet)
        elif not was_ever_generated:
            _pos_mark_table_occupied(conn, table_label, outlet)

    if next_kot_sent and (is_first_kot_send or not existing_kot_no):
        ensure_pos_invoice_kot_no(
            conn,
            invoice_id,
            outlet=outlet,
            order_date=order_date,
        )

    invoice = get_pos_invoice(conn, invoice_id)
    # Generated bills with nothing left to collect — no separate settle step.
    if (
        next_bill_sent
        and invoice
        and _pos_money(invoice.get("grand_total")) <= 0.009
        and str(invoice.get("status") or "open").strip().lower() == "open"
    ):
        invoice = settle_pos_invoice(
            conn,
            invoice_id,
            payment_splits=[],
            notes="",
        )
    return invoice


def auto_settle_zero_payable_pos_invoices(conn, *, outlet=None):
    """Close open, generated POS bills whose grand total is already zero.

    Repairs legacy rows that stayed Unsettled after a 100% discount (or other
    zero-payable) Generate Invoice before auto-settle existed.
    Also drops ₹0 tender rows so Payment Mode shows Settled, not Cash.
    """
    ensure_pos_schema(conn)
    clauses = [
        "is_active = 1",
        "lower(COALESCE(status, 'open')) = 'open'",
        "COALESCE(customer_bill_sent, 0) = 1",
        "COALESCE(grand_total, 0) <= 0.009",
    ]
    params = []
    if outlet is not None:
        clauses.append("outlet = ?")
        params.append(normalize_pos_outlet(outlet))
    rows = conn.execute(
        f"""
        SELECT id
        FROM pos_invoices
        WHERE {" AND ".join(clauses)}
        ORDER BY id ASC
        """,
        params,
    ).fetchall()
    settled = []
    for row in rows:
        try:
            settled.append(
                settle_pos_invoice(
                    conn,
                    int(row["id"]),
                    payment_splits=[],
                    notes="",
                )
            )
        except ValueError:
            continue
    # Complimentary / zero-payable bills may still have a historical ₹0 Cash row.
    zero_pay_clauses = [
        "i.is_active = 1",
        "COALESCE(i.grand_total, 0) <= 0.009",
        "COALESCE(i.customer_bill_sent, 0) = 1",
    ]
    zero_pay_params = []
    if outlet is not None:
        zero_pay_clauses.append("i.outlet = ?")
        zero_pay_params.append(normalize_pos_outlet(outlet))
    cur = conn.execute(
        f"""
        DELETE FROM pos_invoice_payments
        WHERE invoice_id IN (
            SELECT i.id FROM pos_invoices i
            WHERE {" AND ".join(zero_pay_clauses)}
        )
        AND COALESCE(amount, 0) <= 0.009
        """,
        zero_pay_params,
    )
    cleaned = int(cur.rowcount or 0)
    return {"settled": settled, "cleaned_payments": cleaned, "changed": bool(settled or cleaned)}


def get_pos_invoice(conn, invoice_id):
    """Return one active invoice with lines, or None."""
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError):
        return None
    row = conn.execute(
        """
        SELECT
            i.*,
            (
                SELECT COUNT(*) FROM pos_invoice_lines l WHERE l.invoice_id = i.id
            ) AS item_count
        FROM pos_invoices i
        WHERE i.id = ? AND i.is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    invoice = _pos_invoice_row_to_dict(conn, row, include_lines=True)
    if invoice:
        _apply_pos_invoice_payment_modes(conn, invoice)
        invoice["payments"] = list_pos_invoice_payments(conn, invoice_id)
    return invoice


def soft_delete_pos_invoice(conn, invoice_id):
    """Soft-delete an invoice. Raises ValueError if missing."""
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        "SELECT id, order_no, outlet FROM pos_invoices WHERE id = ? AND is_active = 1",
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    if _pos_is_official_order_no(row["order_no"], row["outlet"] if "outlet" in row.keys() else None):
        raise ValueError("Issued invoice numbers cannot be removed; cancel the invoice instead.")
    conn.execute(
        f"""
        UPDATE pos_invoices
        SET is_active = 0, updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (invoice_id,),
    )
    return True


def cancel_pos_invoice(conn, invoice_id, reason="", cancelled_by=""):
    """Cancel an unsettled invoice.

    Issued official numbers (SPC|INV/{yy-yy}/{n}) stay on an active row with
    status='cancelled' so the series is never reused and sales can audit the
    void. Provisional drafts are soft-deleted (no series to protect).
    Returns a dict: {\"mode\": \"cancelled\"|\"deleted\", \"invoice\": ...|None}.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    invoice = get_pos_invoice(conn, invoice_id)
    if not invoice:
        raise ValueError("Invoice not found.")
    status = str(invoice.get("status") or "open").strip().lower() or "open"
    if status == "closed":
        raise ValueError("Settled invoices cannot be cancelled.")
    if status == "cancelled":
        return {"mode": "cancelled", "invoice": invoice}
    reason_text = " ".join(str(reason or "").split()).strip()[:500]
    if not reason_text:
        raise ValueError("Enter a reason for cancellation.")
    actor = " ".join(str(cancelled_by or "").split()).strip()[:160]

    order_no = str(invoice.get("order_no") or "").strip()
    outlet = normalize_pos_outlet(invoice.get("outlet"))
    cancelled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Generated bills (Generate Invoice) must keep an audit row — never soft-delete,
    # even if the order_no still looks provisional-shaped.
    bill_generated = bool(invoice.get("customer_bill_sent"))
    soft_delete_ok = (
        (not bill_generated)
        and is_provisional_pos_order_no(order_no, outlet)
        and not _pos_is_official_order_no(order_no, outlet)
    )
    if soft_delete_ok:
        # Persist reason briefly so audit tools can read it if needed, then drop.
        conn.execute(
            f"""
            UPDATE pos_invoices
            SET cancel_reason = ?,
                cancelled_at = ?,
                cancelled_by = ?,
                updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (reason_text, cancelled_at, actor, invoice_id),
        )
        soft_delete_pos_invoice(conn, invoice_id)
        return {"mode": "deleted", "invoice": None}

    conn.execute(
        f"""
        UPDATE pos_invoices
        SET status = 'cancelled',
            cancel_reason = ?,
            cancelled_at = ?,
            cancelled_by = ?,
            table_label = CASE
                WHEN order_type = 'dine_in' THEN ''
                ELSE table_label
            END,
            updated_at = {SQL_NOW}
        WHERE id = ?
        """,
        (reason_text, cancelled_at, actor, invoice_id),
    )
    return {"mode": "cancelled", "invoice": get_pos_invoice(conn, invoice_id)}


def reopen_pos_invoice_for_edit(conn, invoice_id):
    """Clear Generate Invoice lock so an unsettled bill can be edited again.

    Refuses settled (closed) and cancelled invoices. Idempotent when
    customer_bill_sent is already 0.
    """
    ensure_pos_schema(conn)
    try:
        invoice_id = int(invoice_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid invoice id.") from exc
    row = conn.execute(
        """
        SELECT id, status, COALESCE(customer_bill_sent, 0) AS customer_bill_sent
        FROM pos_invoices
        WHERE id = ? AND is_active = 1
        """,
        (invoice_id,),
    ).fetchone()
    if not row:
        raise ValueError("Invoice not found.")
    status = str(row["status"] or "open").strip().lower() or "open"
    if status == "closed":
        raise ValueError("Settled invoices cannot be edited. Create a new order instead.")
    if status == "cancelled":
        raise ValueError("Cancelled invoices cannot be edited.")
    if int(row["customer_bill_sent"] or 0):
        conn.execute(
            f"""
            UPDATE pos_invoices
            SET customer_bill_sent = 0,
                updated_at = {SQL_NOW}
            WHERE id = ?
            """,
            (invoice_id,),
        )
    return get_pos_invoice(conn, invoice_id)


def list_pos_invoices(
    conn,
    *,
    date_from=None,
    date_to=None,
    order_type=None,
    settlement=None,
    q="",
    outlet=None,
):
    """List active invoices with optional filters (newest first)."""
    ensure_pos_schema(conn)
    clauses = ["i.is_active = 1"]
    params = []
    if outlet is not None:
        clauses.append("i.outlet = ?")
        params.append(normalize_pos_outlet(outlet))
    if date_from:
        clauses.append("i.order_date >= ?")
        params.append(str(date_from))
    if date_to:
        clauses.append("i.order_date <= ?")
        params.append(str(date_to))
    if order_type and str(order_type).strip().lower() not in ("", "all"):
        clauses.append("i.order_type = ?")
        params.append(_normalize_pos_order_type(order_type))
    settlement_key = str(settlement or "").strip().lower()
    if settlement_key == "settled":
        clauses.append(
            """
            (
                lower(COALESCE(i.status, 'open')) = 'closed'
                OR EXISTS (
                    SELECT 1 FROM pos_invoice_payments p
                    WHERE p.invoice_id = i.id AND COALESCE(p.amount, 0) > 0.009
                )
                OR TRIM(COALESCE(i.settled_at, '')) != ''
            )
            """
        )
    elif settlement_key == "unsettled":
        clauses.append(
            """
            lower(COALESCE(i.status, 'open')) = 'open'
            AND NOT EXISTS (
                SELECT 1 FROM pos_invoice_payments p
                WHERE p.invoice_id = i.id AND COALESCE(p.amount, 0) > 0.009
            )
            AND TRIM(COALESCE(i.settled_at, '')) = ''
            """
        )
    needle = " ".join(str(q or "").split()).strip().lower()
    if needle:
        like = f"%{needle}%"
        clauses.append(
            """
            (
                lower(i.order_no) LIKE ?
                OR lower(i.customer_name) LIKE ?
                OR lower(i.customer_mobile) LIKE ?
                OR lower(i.table_label) LIKE ?
                OR lower(i.captain) LIKE ?
            )
            """
        )
        params.extend([like, like, like, like, like])
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            i.*,
            (
                SELECT COUNT(*) FROM pos_invoice_lines l WHERE l.invoice_id = i.id
            ) AS item_count
        FROM pos_invoices i
        WHERE {where}
        ORDER BY i.order_date DESC, i.saved_at DESC, i.id DESC
        """,
        params,
    ).fetchall()
    invoices = [_pos_invoice_row_to_dict(conn, row, include_lines=False) for row in rows]
    return _enrich_pos_invoices_payment_modes(conn, invoices)


def _pos_outlet_display_label(outlet) -> str:
    key = normalize_pos_outlet(outlet)
    if key == POS_OUTLET_BAR:
        return "Bar"
    return "Restaurant"


def _pos_menu_sales_invoice_clauses(
    *,
    date_from=None,
    date_to=None,
    outlet=None,
    settlement=None,
    category_id=None,
):
    """Shared WHERE clauses/params for menu sales aggregations."""
    clauses = [
        "i.is_active = 1",
        "lower(COALESCE(i.status, 'open')) != 'cancelled'",
    ]
    params = []
    outlet_key = str(outlet or "").strip().lower()
    if outlet_key in (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR):
        clauses.append("i.outlet = ?")
        params.append(normalize_pos_outlet(outlet_key))
    elif outlet_key not in ("", "all"):
        clauses.append("i.outlet = ?")
        params.append(normalize_pos_outlet(outlet_key))
    if date_from:
        clauses.append("i.order_date >= ?")
        params.append(str(date_from))
    if date_to:
        clauses.append("i.order_date <= ?")
        params.append(str(date_to))
    settlement_key = str(settlement or "").strip().lower()
    if settlement_key == "settled":
        clauses.append(
            """
            (
                EXISTS (
                    SELECT 1 FROM pos_invoice_payments p WHERE p.invoice_id = i.id
                )
                OR TRIM(COALESCE(i.settled_at, '')) != ''
            )
            """
        )
    elif settlement_key == "unsettled":
        clauses.append(
            """
            NOT EXISTS (
                SELECT 1 FROM pos_invoice_payments p WHERE p.invoice_id = i.id
            )
            AND TRIM(COALESCE(i.settled_at, '')) = ''
            AND lower(COALESCE(i.status, 'open')) = 'open'
            """
        )
    try:
        cat_id = int(category_id) if category_id not in (None, "", 0, "0") else 0
    except (TypeError, ValueError):
        cat_id = 0
    if cat_id > 0:
        clauses.append("m.category_id = ?")
        params.append(cat_id)
    return clauses, params


def list_pos_menu_sales(
    conn,
    *,
    date_from=None,
    date_to=None,
    outlet=None,
    settlement=None,
    category_id=None,
):
    """Item-wise POS sales: order count, qty sold, rate, and sale value per menu item."""
    ensure_pos_schema(conn)
    clauses, params = _pos_menu_sales_invoice_clauses(
        date_from=date_from,
        date_to=date_to,
        outlet=outlet,
        settlement=settlement,
        category_id=category_id,
    )
    where = " AND ".join(clauses)
    rows = conn.execute(
        f"""
        SELECT
            COALESCE(l.menu_item_id, 0) AS menu_item_id,
            COALESCE(
                NULLIF(TRIM(m.name), ''),
                NULLIF(TRIM(l.name), ''),
                'Item'
            ) AS item_name,
            COALESCE(c.id, 0) AS category_id,
            COALESCE(c.name, '') AS category_name,
            i.outlet AS outlet,
            COUNT(DISTINCT i.id) AS order_count,
            COALESCE(SUM(l.qty), 0) AS qty_sold,
            COALESCE(SUM(l.line_total), 0) AS sale_value
        FROM pos_invoice_lines l
        JOIN pos_invoices i ON i.id = l.invoice_id
        LEFT JOIN pos_menu_items m ON m.id = l.menu_item_id
        LEFT JOIN pos_menu_categories c ON c.id = m.category_id
        WHERE {where}
        GROUP BY
            COALESCE(l.menu_item_id, 0),
            COALESCE(
                NULLIF(TRIM(m.name), ''),
                NULLIF(TRIM(l.name), ''),
                'Item'
            ),
            COALESCE(c.id, 0),
            COALESCE(c.name, ''),
            i.outlet
        ORDER BY
            category_name COLLATE NOCASE ASC,
            i.outlet ASC,
            item_name COLLATE NOCASE ASC
        """,
        params,
    ).fetchall()
    results = []
    for row in rows:
        outlet_key = normalize_pos_outlet(row["outlet"])
        qty_sold = float(row["qty_sold"] or 0)
        sale_value = round(float(row["sale_value"] or 0), 2)
        rate = round(sale_value / qty_sold, 2) if qty_sold > 0 else 0.0
        results.append(
            {
                "menu_item_id": int(row["menu_item_id"] or 0),
                "item_name": str(row["item_name"] or "Item").strip() or "Item",
                "category_id": int(row["category_id"] or 0),
                "category_name": str(row["category_name"] or "").strip(),
                "outlet": outlet_key,
                "outlet_label": _pos_outlet_display_label(outlet_key),
                "order_count": int(row["order_count"] or 0),
                "qty_sold": qty_sold,
                "rate": rate,
                "sale_value": sale_value,
            }
        )
    return results


def _menu_sales_qty_display(qty):
    value = float(qty or 0)
    if abs(value - round(value)) > 0.0001:
        return round(value, 3)
    return int(round(value))


def group_pos_menu_sales_by_category(rows, *, include_outlet_label=False):
    """Group item-wise menu sales by category for the Item Wise Sales Report."""
    groups_map = {}
    order = []
    for row in list(rows or []):
        cat_id = int(row.get("category_id") or 0)
        cat_name = str(row.get("category_name") or "").strip() or "Uncategorized"
        outlet = str(row.get("outlet") or "")
        outlet_label = str(row.get("outlet_label") or "").strip()
        key = (outlet, cat_id, cat_name.casefold())
        if key not in groups_map:
            display = cat_name
            if include_outlet_label and outlet_label:
                display = f"{cat_name} ({outlet_label})"
            groups_map[key] = {
                "category_id": cat_id,
                "category_name": display,
                "outlet": outlet,
                "outlet_label": outlet_label,
                "item_rows": [],
                "qty_sum": 0.0,
                "sale_sum": 0.0,
            }
            order.append(key)
        group = groups_map[key]
        group["item_rows"].append(row)
        group["qty_sum"] += float(row.get("qty_sold") or 0)
        group["sale_sum"] += float(row.get("sale_value") or 0)

    results = []
    for key in order:
        group = groups_map[key]
        group["qty_sum"] = _menu_sales_qty_display(group["qty_sum"])
        group["sale_sum"] = round(group["sale_sum"], 2)
        results.append(group)
    return results


def pos_menu_sales_kpis(rows, conn=None, *, date_from=None, date_to=None, outlet=None, settlement=None, category_id=None):
    """KPIs for menu sales: items, qty, sale value, contributing invoices."""
    item_rows = list(rows or [])
    qty_sum = 0.0
    sale_sum = 0.0
    for row in item_rows:
        qty_sum += float(row.get("qty_sold") or 0)
        sale_sum += float(row.get("sale_value") or 0)
    invoice_count = 0
    if conn is not None:
        clauses, params = _pos_menu_sales_invoice_clauses(
            date_from=date_from,
            date_to=date_to,
            outlet=outlet,
            settlement=settlement,
            category_id=category_id,
        )
        where = " AND ".join(clauses)
        # Only count invoices that actually have lines matching the filters.
        count_row = conn.execute(
            f"""
            SELECT COUNT(DISTINCT i.id) AS n
            FROM pos_invoices i
            JOIN pos_invoice_lines l ON l.invoice_id = i.id
            LEFT JOIN pos_menu_items m ON m.id = l.menu_item_id
            WHERE {where}
            """,
            params,
        ).fetchone()
        invoice_count = int((count_row["n"] if count_row else 0) or 0)
    return {
        "item_count": len(item_rows),
        "qty_sum": round(qty_sum, 3) if abs(qty_sum - round(qty_sum)) > 0.0001 else int(round(qty_sum)),
        "sale_value_sum": round(sale_sum, 2),
        "invoice_count": invoice_count,
    }


def _customer_insights_empty_row(mobile, name=""):
    return {
        "mobile": mobile,
        "customer_name": str(name or "").strip() or "Guest",
        "order_count": 0,
        "top_item": "",
        "restaurant_value": 0.0,
        "bar_value": 0.0,
        "hotel_value": 0.0,
        "total_value": 0.0,
        "_top_item": "",
    }


def _customer_insights_identity(mobile, name=""):
    """Stable customer key: 10-digit mobile when present, else normalized name."""
    digits = _normalize_customer_mobile(mobile)
    display_name = " ".join(str(name or "").split()).strip() or "Guest"
    if len(digits) == 10:
        return f"m:{digits}", digits, display_name
    return f"n:{display_name.casefold()}", "", display_name


def list_customer_insights(
    conn,
    *,
    date_from=None,
    date_to=None,
    channel=None,
    settlement=None,
):
    """Per-customer spend + top POS item across Restaurant, Bar, and Hotel.

    Identity is a normalized 10-digit mobile when present. Imported POS bills
    often have a guest name but no mobile — those still appear, grouped by name.
    """
    ensure_pos_schema(conn)
    ensure_customers_schema(conn)
    ensure_hotel_room_invoices_schema(conn)

    channel_key = str(channel or "all").strip().lower()
    if channel_key not in ("all", "restaurant", "bar", "hotel"):
        channel_key = "all"
    include_pos = channel_key in ("all", "restaurant", "bar")
    include_hotel = channel_key in ("all", "hotel")
    pos_outlet = None
    if channel_key in (POS_OUTLET_RESTAURANT, POS_OUTLET_BAR):
        pos_outlet = channel_key

    by_key = {}

    def _ensure(mobile, name=""):
        key, digits, display_name = _customer_insights_identity(mobile, name)
        row = by_key.get(key)
        if row is None:
            row = _customer_insights_empty_row(digits, display_name)
            by_key[key] = row
        elif display_name and (
            not row["customer_name"] or row["customer_name"] == "Guest"
        ):
            row["customer_name"] = display_name
        if digits and not row["mobile"]:
            row["mobile"] = digits
        return row

    if include_pos:
        clauses, params = _pos_menu_sales_invoice_clauses(
            date_from=date_from,
            date_to=date_to,
            outlet=pos_outlet,
            settlement=settlement,
            category_id=None,
        )
        where = " AND ".join(clauses)

        inv_rows = conn.execute(
            f"""
            SELECT
                i.outlet AS outlet,
                i.customer_mobile AS customer_mobile,
                MAX(NULLIF(TRIM(i.customer_name), '')) AS customer_name,
                COUNT(*) AS order_count,
                COALESCE(SUM(i.grand_total), 0) AS grand_total
            FROM pos_invoices i
            WHERE {where}
            GROUP BY
                i.outlet,
                TRIM(COALESCE(i.customer_mobile, '')),
                lower(TRIM(COALESCE(i.customer_name, '')))
            """,
            params,
        ).fetchall()
        for row in inv_rows:
            bucket = _ensure(row["customer_mobile"], row["customer_name"] or "")
            bucket["order_count"] += int(row["order_count"] or 0)
            outlet_key = normalize_pos_outlet(row["outlet"])
            value = round(float(row["grand_total"] or 0), 2)
            if outlet_key == POS_OUTLET_BAR:
                bucket["bar_value"] = round(bucket["bar_value"] + value, 2)
            else:
                bucket["restaurant_value"] = round(
                    bucket["restaurant_value"] + value, 2
                )

        # One top item per customer identity (avoids shipping every item×customer combo).
        item_rows = conn.execute(
            f"""
            WITH item_qty AS (
                SELECT
                    TRIM(COALESCE(i.customer_mobile, '')) AS customer_mobile,
                    TRIM(COALESCE(i.customer_name, '')) AS customer_name,
                    COALESCE(
                        NULLIF(TRIM(m.name), ''),
                        NULLIF(TRIM(l.name), ''),
                        'Item'
                    ) AS item_name,
                    COALESCE(SUM(l.qty), 0) AS qty_sold
                FROM pos_invoice_lines l
                JOIN pos_invoices i ON i.id = l.invoice_id
                LEFT JOIN pos_menu_items m ON m.id = l.menu_item_id
                WHERE {where}
                GROUP BY
                    TRIM(COALESCE(i.customer_mobile, '')),
                    TRIM(COALESCE(i.customer_name, '')),
                    COALESCE(
                        NULLIF(TRIM(m.name), ''),
                        NULLIF(TRIM(l.name), ''),
                        'Item'
                    )
            ),
            ranked AS (
                SELECT
                    customer_mobile,
                    customer_name,
                    item_name,
                    ROW_NUMBER() OVER (
                        PARTITION BY customer_mobile, lower(TRIM(customer_name))
                        ORDER BY qty_sold DESC, item_name COLLATE NOCASE ASC
                    ) AS rn
                FROM item_qty
            )
            SELECT customer_mobile, customer_name, item_name
            FROM ranked
            WHERE rn = 1
            """,
            params,
        ).fetchall()
        for row in item_rows:
            bucket = _ensure(row["customer_mobile"], row["customer_name"] or "")
            item_name = str(row["item_name"] or "Item").strip() or "Item"
            bucket["_top_item"] = item_name

    if include_hotel:
        hotel_clauses = ["1 = 1"]
        hotel_params = []
        hotel_clauses.append(_HOTEL_INVOICE_STAY_SOURCE_SQL)
        if date_from:
            # Prefix range keeps idx_hotel_room_invoices_generated usable.
            hotel_clauses.append("invoice_generated_at >= ?")
            hotel_params.append(str(date_from))
        if date_to:
            try:
                end_exclusive = (
                    datetime.strptime(str(date_to)[:10], "%Y-%m-%d").date()
                    + timedelta(days=1)
                ).isoformat()
            except ValueError:
                end_exclusive = str(date_to) + "\uffff"
            hotel_clauses.append("invoice_generated_at < ?")
            hotel_params.append(end_exclusive)
        settlement_key = str(settlement or "").strip().lower()
        if settlement_key == "settled":
            hotel_clauses.append("LOWER(TRIM(COALESCE(status, ''))) = 'settled'")
        elif settlement_key == "unsettled":
            hotel_clauses.append("LOWER(TRIM(COALESCE(status, ''))) != 'settled'")
        # Prefer JSON1 extract so we never pull/parse full payload blobs.
        hotel_clauses.append(
            """
            (
                LENGTH(TRIM(COALESCE(
                    json_extract(payload_json, '$.stay.mobile'),
                    json_extract(payload_json, '$.mobile'),
                    ''
                ))) >= 8
            )
            """
        )
        hotel_where = " AND ".join(hotel_clauses)
        hotel_rows = conn.execute(
            f"""
            SELECT
                COALESCE(
                    json_extract(payload_json, '$.stay.mobile'),
                    json_extract(payload_json, '$.mobile'),
                    ''
                ) AS mobile_raw,
                MAX(NULLIF(TRIM(guest_name), '')) AS guest_name,
                COUNT(*) AS order_count,
                COALESCE(SUM(estimated_total), 0) AS hotel_value
            FROM hotel_room_invoices
            WHERE {hotel_where}
            GROUP BY mobile_raw
            """,
            hotel_params,
        ).fetchall()
        for row in hotel_rows:
            mobile = _hotel_guest_profile_key(row["mobile_raw"])
            if len(mobile) != 10:
                continue
            guest = str(row["guest_name"] or "").strip() or "Guest"
            bucket = _ensure(mobile, guest)
            bucket["order_count"] += int(row["order_count"] or 0)
            value = round(float(row["hotel_value"] or 0), 2)
            bucket["hotel_value"] = round(bucket["hotel_value"] + value, 2)

    # Prefer Customer Master names when present.
    master_mobiles = [
        row["mobile"] for row in by_key.values() if len(row.get("mobile") or "") == 10
    ]
    if master_mobiles:
        placeholders = ",".join("?" for _ in master_mobiles)
        master_rows = conn.execute(
            f"""
            SELECT mobile, first_name
            FROM customers
            WHERE mobile IN ({placeholders})
            """,
            master_mobiles,
        ).fetchall()
        for row in master_rows:
            key = _normalize_customer_mobile(row["mobile"])
            bucket = by_key.get(f"m:{key}")
            if not bucket:
                continue
            name = str(row["first_name"] or "").strip()
            if name:
                bucket["customer_name"] = name

    results = []
    for bucket in by_key.values():
        top_item = str(bucket.pop("_top_item", "") or "").strip()
        total = round(
            float(bucket["restaurant_value"])
            + float(bucket["bar_value"])
            + float(bucket["hotel_value"]),
            2,
        )
        results.append(
            {
                "mobile": bucket["mobile"],
                "customer_name": bucket["customer_name"] or "Guest",
                "order_count": int(bucket["order_count"] or 0),
                "top_item": top_item,
                "restaurant_value": round(float(bucket["restaurant_value"]), 2),
                "bar_value": round(float(bucket["bar_value"]), 2),
                "hotel_value": round(float(bucket["hotel_value"]), 2),
                "total_value": total,
            }
        )

    results.sort(
        key=lambda r: (-float(r.get("total_value") or 0), str(r.get("customer_name") or "").lower())
    )
    return results


def customer_insights_kpis(rows):
    """KPIs for customer insights list."""
    rows = list(rows or [])
    restaurant = 0.0
    bar = 0.0
    hotel = 0.0
    orders = 0
    for row in rows:
        restaurant += float(row.get("restaurant_value") or 0)
        bar += float(row.get("bar_value") or 0)
        hotel += float(row.get("hotel_value") or 0)
        orders += int(row.get("order_count") or 0)
    total = round(restaurant + bar + hotel, 2)
    return {
        "customer_count": len(rows),
        "order_count": orders,
        "restaurant_value_sum": round(restaurant, 2),
        "bar_value_sum": round(bar, 2),
        "hotel_value_sum": round(hotel, 2),
        "total_value_sum": total,
    }


def list_pos_today_invoices(conn, *, today=None, outlet=POS_OUTLET_RESTAURANT):
    """Active POS invoices for the business day — Tables Invoice hub.

    Includes dine-in and other order types created today (open and closed).
    Newest first via list_pos_invoices ordering (saved_at / id).
    """
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    else:
        today = str(today)
    invoices = list_pos_invoices(
        conn, date_from=today, date_to=today, outlet=normalize_pos_outlet(outlet)
    )
    unsettled = pos_unsettled_today_summary_from_invoices(invoices)
    sales_total = 0.0
    sales_count = 0
    for inv in invoices:
        status = str((inv or {}).get("status") or "open").lower()
        if status == "cancelled":
            continue
        sales_count += 1
        sales_total += _pos_money(inv.get("grand_total"))
    return {
        "date": today,
        "invoice_count": len(invoices),
        "invoices": invoices,
        "sales_total": _pos_money(sales_total),
        "sales_count": sales_count,
        "unsettled_count": unsettled["unsettled_count"],
        "unsettled_total": unsettled["unsettled_total"],
    }


def pos_unsettled_today_summary_from_invoices(invoices):
    """Sum open (not closed/cancelled) invoice totals from a today-invoice list."""
    total = 0.0
    count = 0
    for inv in invoices or []:
        status = str((inv or {}).get("status") or "open").lower()
        if status in ("closed", "cancelled"):
            continue
        count += 1
        total += _pos_money((inv or {}).get("grand_total"))
    return {
        "unsettled_count": count,
        "unsettled_total": _pos_money(total),
    }


def pos_unsettled_today_summary(conn, *, today=None, outlet=POS_OUTLET_RESTAURANT):
    """Today's open POS invoices — count + grand total for Tables KPI."""
    payload = list_pos_today_invoices(conn, today=today, outlet=outlet)
    return {
        "unsettled_count": payload["unsettled_count"],
        "unsettled_total": payload["unsettled_total"],
    }


def pos_today_sales_summary(conn, *, today=None, outlet=POS_OUTLET_RESTAURANT):
    """Today's POS invoice sales — grand total + count for Tables KPI."""
    payload = list_pos_today_invoices(conn, today=today, outlet=outlet)
    return {
        "sales_total": payload["sales_total"],
        "sales_count": payload["sales_count"],
        "unsettled_count": payload["unsettled_count"],
        "unsettled_total": payload["unsettled_total"],
    }


def pos_invoice_kpis(conn, invoices, *, today=None):
    """Compute ledger KPIs from an already-filtered invoice list."""
    ensure_pos_schema(conn)
    if today is None:
        today = datetime.now().strftime("%Y-%m-%d")
    else:
        today = str(today)
    total_sales = 0.0
    today_sales = 0.0
    today_count = 0
    counted = 0
    payment_totals = _empty_pos_payment_amounts()
    for inv in invoices or []:
        status = str((inv or {}).get("status") or "open").lower()
        if status == "cancelled":
            continue
        amount = _pos_money(inv.get("grand_total"))
        total_sales += amount
        counted += 1
        if str(inv.get("order_date") or "") == today:
            today_sales += amount
            today_count += 1
        amounts = inv.get("payment_amounts")
        if not isinstance(amounts, dict):
            amounts = _empty_pos_payment_amounts()
        for key in POS_LEDGER_PAYMENT_AMOUNT_KEYS:
            payment_totals[key] = _pos_money(
                payment_totals[key] + _pos_money(amounts.get(key))
            )
    count = counted
    average = (total_sales / count) if count else 0.0
    return {
        "total_sales": _pos_money(total_sales),
        "invoice_count": count,
        "average_bill": _pos_money(average),
        "today_sales": _pos_money(today_sales),
        "today_count": today_count,
        "payment_totals": payment_totals,
    }


def _migrate_suppliers_optional_gst(cursor):
    """Allow blank GST on multiple suppliers; keep uniqueness only when GST is set."""
    row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='suppliers'"
    ).fetchone()
    if not row:
        return
    compact = " ".join((row["sql"] or "").split()).upper()
    if "GST TEXT NOT NULL UNIQUE" not in compact:
        return

    cursor.execute("""
        CREATE TABLE suppliers__gst_optional (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL,
            gst                 TEXT    NOT NULL DEFAULT '',
            address             TEXT    NOT NULL DEFAULT '',
            phone               TEXT    NOT NULL DEFAULT '',
            bank_name           TEXT    NOT NULL DEFAULT '',
            bank_account_number TEXT    NOT NULL DEFAULT '',
            ifsc_code           TEXT    NOT NULL DEFAULT '',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        INSERT INTO suppliers__gst_optional
            (id, name, gst, address, phone, bank_name, bank_account_number, ifsc_code, created_at, updated_at)
        SELECT id, name, COALESCE(gst, ''), address, phone, bank_name, bank_account_number, ifsc_code,
               created_at, updated_at
        FROM suppliers
    """)
    cursor.execute("DROP TABLE suppliers")
    cursor.execute("ALTER TABLE suppliers__gst_optional RENAME TO suppliers")


def ensure_cash_ledger_schema(conn):
    """Create cash ledger load/transfer tables if missing (e.g. after DB restore)."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cash_ledger_loads (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT    NOT NULL,
            load_date   TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            amount      REAL    NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cash_ledger_loads_scope
        ON cash_ledger_loads(company, load_date)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cash_ledger_transfers (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            company       TEXT    NOT NULL,
            transfer_date TEXT    NOT NULL,
            destination   TEXT    NOT NULL DEFAULT 'bank',
            description   TEXT    NOT NULL DEFAULT '',
            amount        REAL    NOT NULL DEFAULT 0,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cash_ledger_transfers_scope
        ON cash_ledger_transfers(company, transfer_date)
    """)
    conn.commit()


def ensure_back_office_receipt_schema(conn):
    """Incoming hotel advance / payment receipts (Back Office Receipt ledger)."""
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS back_office_receipt_seq (
            fiscal_year TEXT PRIMARY KEY,
            last_seq    INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS back_office_receipts (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_no       TEXT    NOT NULL UNIQUE,
            fiscal_year      TEXT    NOT NULL,
            seq              INTEGER NOT NULL,
            receipt_date     TEXT    NOT NULL,
            payer_name       TEXT    NOT NULL DEFAULT '',
            agency_id        INTEGER,
            amount           REAL    NOT NULL DEFAULT 0,
            amount_words     TEXT    NOT NULL DEFAULT '',
            payment_mode     TEXT    NOT NULL DEFAULT 'cash',
            instrument_no    TEXT    NOT NULL DEFAULT '',
            instrument_date  TEXT,
            towards          TEXT    NOT NULL DEFAULT '',
            created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            created_by       INTEGER,
            FOREIGN KEY (agency_id) REFERENCES agencies(id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_back_office_receipts_date
        ON back_office_receipts(receipt_date DESC, id DESC)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_back_office_receipts_agency
        ON back_office_receipts(agency_id)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS back_office_receipt_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            hotel_credit_payment_id INTEGER,
            hotel_invoice_number TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (receipt_id) REFERENCES back_office_receipts(id)
        )
        """
    )
    alloc_cols = {
        row["name"]
        for row in cursor.execute("PRAGMA table_info(back_office_receipt_allocations)").fetchall()
    }
    if "hotel_invoice_number" not in alloc_cols:
        cursor.execute(
            """
            ALTER TABLE back_office_receipt_allocations
            ADD COLUMN hotel_invoice_number TEXT NOT NULL DEFAULT ''
            """
        )
    # Legacy rows required hotel_credit_payment_id NOT NULL. Rebuild if still constrained.
    notnull_credit = False
    for row in cursor.execute("PRAGMA table_info(back_office_receipt_allocations)").fetchall():
        if row["name"] == "hotel_credit_payment_id" and int(row["notnull"] or 0) == 1:
            notnull_credit = True
            break
    if notnull_credit:
        cursor.execute(
            """
            CREATE TABLE back_office_receipt_allocations_v2 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id INTEGER NOT NULL,
                hotel_credit_payment_id INTEGER,
                hotel_invoice_number TEXT NOT NULL DEFAULT '',
                amount REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (receipt_id) REFERENCES back_office_receipts(id)
            )
            """
        )
        cursor.execute(
            """
            INSERT INTO back_office_receipt_allocations_v2
                (id, receipt_id, hotel_credit_payment_id, hotel_invoice_number, amount, created_at)
            SELECT id, receipt_id, hotel_credit_payment_id,
                   COALESCE(hotel_invoice_number, ''), amount, created_at
            FROM back_office_receipt_allocations
            """
        )
        cursor.execute("DROP TABLE back_office_receipt_allocations")
        cursor.execute(
            "ALTER TABLE back_office_receipt_allocations_v2 RENAME TO back_office_receipt_allocations"
        )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bor_alloc_receipt
        ON back_office_receipt_allocations(receipt_id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bor_alloc_payment
        ON back_office_receipt_allocations(hotel_credit_payment_id)
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_bor_alloc_invoice
        ON back_office_receipt_allocations(hotel_invoice_number)
        """
    )
    # Migrate legacy display format ``26-27 / 1`` → ``HBE/BOR/26-27/1``.
    legacy_rows = cursor.execute(
        """
        SELECT id, receipt_no, fiscal_year, seq
        FROM back_office_receipts
        WHERE receipt_no LIKE '% / %'
           AND receipt_no NOT LIKE 'HBE/BOR/%'
        """
    ).fetchall()
    for row in legacy_rows:
        short_fy = str(row["fiscal_year"] or "").strip() or indian_fiscal_year_short_label()
        seq = int(row["seq"] or 0)
        if seq <= 0:
            continue
        new_no = f"HBE/BOR/{short_fy}/{seq}"
        cursor.execute(
            "UPDATE back_office_receipts SET receipt_no = ? WHERE id = ?",
            (new_no, int(row["id"])),
        )
    conn.commit()


def next_back_office_receipt_seq(conn, fiscal_year=None):
    """Next Back Office Receipt sequence for the Indian fiscal year (short label)."""
    ensure_back_office_receipt_schema(conn)
    fy = str(fiscal_year or "").strip()
    if not fy:
        fy = indian_fiscal_year_label()
    short_fy = indian_fiscal_year_short_label(fy)
    row = conn.execute(
        "SELECT last_seq FROM back_office_receipt_seq WHERE fiscal_year = ?",
        (short_fy,),
    ).fetchone()
    stored = int(row["last_seq"] or 0) if row else 0
    nxt = stored + 1
    conn.execute(
        """
        INSERT INTO back_office_receipt_seq (fiscal_year, last_seq)
        VALUES (?, ?)
        ON CONFLICT(fiscal_year) DO UPDATE SET last_seq = excluded.last_seq
        """,
        (short_fy, nxt),
    )
    return short_fy, nxt


def allocate_back_office_receipt_no(conn, when=None):
    """Allocate display number like ``HBE/BOR/26-27/1``."""
    fy = indian_fiscal_year_label(when)
    short_fy, seq = next_back_office_receipt_seq(conn, fy)
    return short_fy, seq, f"HBE/BOR/{short_fy}/{seq}"


def ensure_stores_schema(conn):
    """Create Stores inventory workflow tables if missing."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_indents (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet        TEXT    NOT NULL,
            indent_no     TEXT    NOT NULL UNIQUE,
            status        TEXT    NOT NULL DEFAULT 'draft',
            notes         TEXT    NOT NULL DEFAULT '',
            created_by    INTEGER,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            submitted_at  TEXT,
            decided_by    INTEGER,
            decided_at    TEXT,
            decision_note TEXT    NOT NULL DEFAULT '',
            FOREIGN KEY (created_by) REFERENCES users(id),
            FOREIGN KEY (decided_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_indents_outlet_status
        ON store_indents(outlet, status, created_at DESC)
    """)
    indent_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_indents)").fetchall()
    }
    if "submission_token" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN submission_token TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_store_indents_submission_token
        ON store_indents(submission_token) WHERE submission_token != ''
    """)
    # Refresh columns after possible ALTER above.
    indent_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_indents)").fetchall()
    }
    if "approval_token" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN approval_token TEXT NOT NULL DEFAULT ''"
        )
    if "wa_decided_by" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_decided_by TEXT NOT NULL DEFAULT ''"
        )
    if "wa_decision_message_id" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_decision_message_id TEXT NOT NULL DEFAULT ''"
        )
    if "wa_template_message_id" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_template_message_id TEXT NOT NULL DEFAULT ''"
        )
    if "wa_interactive_message_id" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_interactive_message_id TEXT NOT NULL DEFAULT ''"
        )
    if "wa_notify_lock" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_notify_lock INTEGER NOT NULL DEFAULT 0"
        )
    if "wa_notify_lock_at" not in indent_cols:
        cursor.execute(
            "ALTER TABLE store_indents ADD COLUMN wa_notify_lock_at TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_store_indents_approval_token
        ON store_indents(approval_token) WHERE approval_token != ''
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_indent_lines (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id          INTEGER NOT NULL,
            item_name          TEXT    NOT NULL,
            quantity           REAL    NOT NULL DEFAULT 0,
            quantity_received  REAL    NOT NULL DEFAULT 0,
            unit               TEXT    NOT NULL DEFAULT 'pcs',
            notes              TEXT    NOT NULL DEFAULT '',
            approximate_price  REAL,
            FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE
        )
    """)
    indent_line_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_indent_lines)").fetchall()
    }
    if "approximate_price" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN approximate_price REAL"
        )
    if "pack_label" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN pack_label TEXT NOT NULL DEFAULT ''"
        )
    if "pack_qty_in_base" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN pack_qty_in_base REAL"
        )
    if "quantity_received" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN quantity_received REAL NOT NULL DEFAULT 0"
        )
        # Backfill from stock movements for partially received indents wrongly closed as stocked.
        cursor.execute(
            """
            UPDATE store_indent_lines
            SET quantity_received = COALESCE((
                SELECT SUM(m.qty_delta)
                FROM store_stock_movements m
                WHERE m.ref_type = 'stock_inward'
                  AND m.ref_id = store_indent_lines.indent_id
                  AND m.item_name = store_indent_lines.item_name
                  AND m.movement_type = 'receive'
            ), 0)
            WHERE EXISTS (
                SELECT 1 FROM store_indents i
                WHERE i.id = store_indent_lines.indent_id
                  AND i.status = 'stocked'
            )
            """
        )
        cursor.execute(
            """
            UPDATE store_indents
            SET status = 'approved'
            WHERE status = 'stocked'
              AND EXISTS (
                SELECT 1 FROM store_indent_lines l
                WHERE l.indent_id = store_indents.id
                  AND COALESCE(l.quantity, 0) - COALESCE(l.quantity_received, 0) > 0.0001
              )
            """
        )
    if "quantity_ordered" not in indent_line_cols:
        cursor.execute(
            "ALTER TABLE store_indent_lines ADD COLUMN quantity_ordered REAL NOT NULL DEFAULT 0"
        )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_indent_whatsapp_messages (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id        INTEGER NOT NULL,
            recipient_phone  TEXT    NOT NULL DEFAULT '',
            wa_message_id    TEXT    NOT NULL DEFAULT '',
            template_name    TEXT    NOT NULL DEFAULT '',
            status           TEXT    NOT NULL DEFAULT '',
            error_message    TEXT    NOT NULL DEFAULT '',
            created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE
        )
    """)
    wa_msg_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_indent_whatsapp_messages)").fetchall()
    }
    if "approval_token" not in wa_msg_cols:
        cursor.execute(
            "ALTER TABLE store_indent_whatsapp_messages "
            "ADD COLUMN approval_token TEXT NOT NULL DEFAULT ''"
        )
    if "send_kind" not in wa_msg_cols:
        cursor.execute(
            "ALTER TABLE store_indent_whatsapp_messages "
            "ADD COLUMN send_kind TEXT NOT NULL DEFAULT ''"
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_indent_wa_message
        ON store_indent_whatsapp_messages(wa_message_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_indent_wa_indent
        ON store_indent_whatsapp_messages(indent_id, created_at DESC)
    """)
    # One attempt per indent approval round + recipient + kind (template|interactive).
    # Superseded rows fall outside the partial index so a new round can notify again.
    cursor.execute("DROP INDEX IF EXISTS idx_store_indent_wa_send_claim")
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_store_indent_wa_send_claim
        ON store_indent_whatsapp_messages(
            indent_id, recipient_phone, approval_token, send_kind
        )
        WHERE status IN ('sending', 'sent', 'failed')
          AND approval_token != ''
          AND send_kind != ''
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_po_lines (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id   INTEGER NOT NULL,
            line_id     INTEGER NOT NULL UNIQUE,
            supplier_id INTEGER,
            rate        REAL,
            quantity    REAL,
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE,
            FOREIGN KEY (line_id) REFERENCES store_indent_lines(id) ON DELETE CASCADE,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        )
    """)
    po_line_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_po_lines)").fetchall()
    }
    if "quantity" not in po_line_cols:
        cursor.execute("ALTER TABLE store_po_lines ADD COLUMN quantity REAL")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_po_lines_indent
        ON store_po_lines(indent_id)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_po_sends (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id        INTEGER NOT NULL,
            supplier_id      INTEGER,
            phone            TEXT    NOT NULL DEFAULT '',
            message          TEXT    NOT NULL DEFAULT '',
            pdf_name         TEXT    NOT NULL DEFAULT '',
            include_pdf      INTEGER NOT NULL DEFAULT 1,
            conversation_id  INTEGER,
            wa_message_id    TEXT    NOT NULL DEFAULT '',
            status           TEXT    NOT NULL DEFAULT 'sent',
            error            TEXT    NOT NULL DEFAULT '',
            sent_by          INTEGER,
            sent_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id),
            FOREIGN KEY (sent_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_po_sends_indent
        ON store_po_sends(indent_id, sent_at DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_po_sends_sent_at
        ON store_po_sends(sent_at DESC)
    """)
    po_send_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_po_sends)").fetchall()
    }
    if "po_no" not in po_send_cols:
        cursor.execute(
            "ALTER TABLE store_po_sends ADD COLUMN po_no TEXT NOT NULL DEFAULT ''"
        )
    # PO numbers run as PO/{BAR|RES}/{YY-YY}/{n} per outlet + fiscal year.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_po_seq (
            fiscal_year TEXT    PRIMARY KEY,
            last_seq    INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_purchase_orders (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id   INTEGER NOT NULL,
            supplier_id INTEGER NOT NULL,
            po_no       TEXT    NOT NULL UNIQUE,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE,
            FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
        )
    """)
    # Allow multiple POs per indent×supplier when partial quantities remain.
    po_table_sql_row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='store_purchase_orders'"
    ).fetchone()
    po_sql_text = (po_table_sql_row[0] or "") if po_table_sql_row else ""
    if "UNIQUE (indent_id, supplier_id)" in po_sql_text:
        cursor.execute("""
            CREATE TABLE store_purchase_orders_new (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                indent_id   INTEGER NOT NULL,
                supplier_id INTEGER NOT NULL,
                po_no       TEXT    NOT NULL UNIQUE,
                created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (indent_id) REFERENCES store_indents(id) ON DELETE CASCADE,
                FOREIGN KEY (supplier_id) REFERENCES suppliers(id)
            )
        """)
        cursor.execute(
            """
            INSERT INTO store_purchase_orders_new
                (id, indent_id, supplier_id, po_no, created_at)
            SELECT id, indent_id, supplier_id, po_no, created_at
            FROM store_purchase_orders
            """
        )
        cursor.execute("DROP TABLE store_purchase_orders")
        cursor.execute(
            "ALTER TABLE store_purchase_orders_new RENAME TO store_purchase_orders"
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_purchase_orders_indent
        ON store_purchase_orders(indent_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_purchase_orders_indent_supplier
        ON store_purchase_orders(indent_id, supplier_id)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_purchase_order_lines (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_order_id  INTEGER NOT NULL,
            line_id            INTEGER,
            item_name          TEXT    NOT NULL DEFAULT '',
            display_name       TEXT    NOT NULL DEFAULT '',
            quantity           REAL    NOT NULL DEFAULT 0,
            unit               TEXT    NOT NULL DEFAULT '',
            pack_label         TEXT    NOT NULL DEFAULT '',
            pack_qty_in_base   REAL,
            rate               REAL,
            quantity_received  REAL    NOT NULL DEFAULT 0,
            FOREIGN KEY (purchase_order_id) REFERENCES store_purchase_orders(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_purchase_order_lines_po
        ON store_purchase_order_lines(purchase_order_id)
    """)
    po_line_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(store_purchase_order_lines)")
    }
    if "quantity_received" not in po_line_cols:
        cursor.execute(
            "ALTER TABLE store_purchase_order_lines "
            "ADD COLUMN quantity_received REAL NOT NULL DEFAULT 0"
        )

    # Allocate existing indent quantity_received across PO lines (oldest PO first)
    # so fully received POs hide from Stock Inward even when indent qty remains.
    recv_marker = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='store_po_line_received_backfill'"
    ).fetchone()
    if not recv_marker:
        cursor.execute(
            "CREATE TABLE store_po_line_received_backfill (done INTEGER NOT NULL DEFAULT 1)"
        )
        indent_line_ids = [
            int(row["line_id"])
            for row in cursor.execute(
                """
                SELECT DISTINCT line_id
                FROM store_purchase_order_lines
                WHERE line_id IS NOT NULL
                """
            ).fetchall()
            if row["line_id"] is not None
        ]
        for line_id in indent_line_ids:
            indent_row = cursor.execute(
                """
                SELECT COALESCE(quantity_received, 0) AS quantity_received
                FROM store_indent_lines WHERE id = ?
                """,
                (line_id,),
            ).fetchone()
            if not indent_row:
                continue
            try:
                to_allocate = float(indent_row["quantity_received"] or 0)
            except (TypeError, ValueError):
                to_allocate = 0.0
            if to_allocate <= 0.0001:
                continue
            po_lines = cursor.execute(
                """
                SELECT pol.id, COALESCE(pol.quantity, 0) AS quantity
                FROM store_purchase_order_lines pol
                JOIN store_purchase_orders po ON po.id = pol.purchase_order_id
                WHERE pol.line_id = ?
                ORDER BY po.created_at ASC, po.id ASC, pol.id ASC
                """,
                (line_id,),
            ).fetchall()
            for pol in po_lines:
                if to_allocate <= 0.0001:
                    break
                try:
                    po_qty = float(pol["quantity"] or 0)
                except (TypeError, ValueError):
                    po_qty = 0.0
                if po_qty <= 0.0001:
                    continue
                take = po_qty if po_qty <= to_allocate else to_allocate
                cursor.execute(
                    """
                    UPDATE store_purchase_order_lines
                    SET quantity_received = ?
                    WHERE id = ?
                    """,
                    (take, int(pol["id"])),
                )
                to_allocate -= take

    # One-time backfill: issued PO draft qtys become quantity_ordered so remaining
    # indent qty stays visible on Generate. Marker row prevents re-running.
    marker = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='store_po_qty_ordered_backfill'"
    ).fetchone()
    if not marker:
        cursor.execute(
            "CREATE TABLE store_po_qty_ordered_backfill (done INTEGER NOT NULL DEFAULT 1)"
        )
        cursor.execute(
            """
            UPDATE store_indent_lines
            SET quantity_ordered = COALESCE((
                SELECT CASE
                    WHEN pl.quantity IS NOT NULL AND pl.quantity > 0.0001
                    THEN MIN(pl.quantity, store_indent_lines.quantity)
                    ELSE store_indent_lines.quantity
                END
                FROM store_po_lines pl
                WHERE pl.line_id = store_indent_lines.id
                  AND pl.supplier_id IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM store_purchase_orders po
                    WHERE po.indent_id = pl.indent_id
                      AND po.supplier_id = pl.supplier_id
                  )
            ), COALESCE(quantity_ordered, 0))
            WHERE COALESCE(quantity_ordered, 0) <= 0.0001
              AND EXISTS (
                SELECT 1 FROM store_po_lines pl
                WHERE pl.line_id = store_indent_lines.id
                  AND pl.supplier_id IS NOT NULL
                  AND EXISTS (
                    SELECT 1 FROM store_purchase_orders po
                    WHERE po.indent_id = pl.indent_id
                      AND po.supplier_id = pl.supplier_id
                  )
              )
            """
        )
        cursor.execute(
            """
            UPDATE store_po_lines
            SET quantity = (
                SELECT MAX(
                    0,
                    COALESCE(l.quantity, 0) - COALESCE(l.quantity_ordered, 0)
                )
                FROM store_indent_lines l
                WHERE l.id = store_po_lines.line_id
            ),
            updated_at = datetime('now','localtime')
            WHERE EXISTS (
                SELECT 1 FROM store_indent_lines l
                WHERE l.id = store_po_lines.line_id
                  AND COALESCE(l.quantity_ordered, 0) > 0.0001
                  AND COALESCE(l.quantity, 0) - COALESCE(l.quantity_ordered, 0) > 0.0001
            )
            """
        )
        cursor.execute(
            """
            UPDATE store_po_lines
            SET quantity = NULL,
                updated_at = datetime('now','localtime')
            WHERE EXISTS (
                SELECT 1 FROM store_indent_lines l
                WHERE l.id = store_po_lines.line_id
                  AND COALESCE(l.quantity_ordered, 0) > 0.0001
                  AND COALESCE(l.quantity, 0) - COALESCE(l.quantity_ordered, 0) <= 0.0001
            )
            """
        )
        cursor.execute("INSERT INTO store_po_qty_ordered_backfill (done) VALUES (1)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_purchase_requests (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            indent_id   INTEGER,
            outlet      TEXT    NOT NULL,
            pr_no       TEXT    NOT NULL UNIQUE,
            status      TEXT    NOT NULL DEFAULT 'open',
            notes       TEXT    NOT NULL DEFAULT '',
            created_by  INTEGER,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            received_at TEXT,
            FOREIGN KEY (indent_id) REFERENCES store_indents(id),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_prs_outlet_status
        ON store_purchase_requests(outlet, status, created_at DESC)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_purchase_request_lines (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            pr_id   INTEGER NOT NULL,
            item_name TEXT  NOT NULL,
            quantity  REAL  NOT NULL DEFAULT 0,
            unit      TEXT  NOT NULL DEFAULT 'pcs',
            notes     TEXT  NOT NULL DEFAULT '',
            FOREIGN KEY (pr_id) REFERENCES store_purchase_requests(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet      TEXT    NOT NULL,
            place       TEXT    NOT NULL DEFAULT 'warehouse',
            item_name   TEXT    NOT NULL,
            unit        TEXT    NOT NULL DEFAULT 'pcs',
            qty_on_hand REAL    NOT NULL DEFAULT 0,
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(outlet, place, item_name, unit)
        )
    """)
    migrated_stock_place = _migrate_store_stock_items_place(cursor)
    cursor.execute("DROP INDEX IF EXISTS idx_store_stock_outlet")
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_stock_outlet
        ON store_stock_items(outlet, place, item_name)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_movements (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet        TEXT    NOT NULL,
            place         TEXT    NOT NULL DEFAULT 'warehouse',
            item_name     TEXT    NOT NULL,
            unit          TEXT    NOT NULL DEFAULT 'pcs',
            qty_delta     REAL    NOT NULL,
            movement_type TEXT    NOT NULL,
            ref_type      TEXT    NOT NULL DEFAULT '',
            ref_id        INTEGER,
            notes         TEXT    NOT NULL DEFAULT '',
            unit_cost     REAL,
            created_by    INTEGER,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (created_by) REFERENCES users(id)
        )
    """)
    movement_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_stock_movements)").fetchall()
    }
    if "unit_cost" not in movement_cols:
        cursor.execute("ALTER TABLE store_stock_movements ADD COLUMN unit_cost REAL")
    if "place" not in movement_cols:
        cursor.execute(
            "ALTER TABLE store_stock_movements ADD COLUMN place TEXT NOT NULL DEFAULT 'warehouse'"
        )
        cursor.execute(
            """
            UPDATE store_stock_movements
            SET place = 'warehouse'
            WHERE place IS NULL OR trim(place) = ''
               OR lower(place) NOT IN ('warehouse', 'counter')
            """
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_movements_outlet
        ON store_stock_movements(outlet, created_at DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_movements_outlet_place
        ON store_stock_movements(outlet, place, created_at DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_movements_ref_item
        ON store_stock_movements(ref_type, item_name, id)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_product_categories (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_product_units (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL UNIQUE COLLATE NOCASE,
            sort_order INTEGER NOT NULL DEFAULT 0,
            is_active  INTEGER NOT NULL DEFAULT 1,
            created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    _seed_store_product_units(cursor)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_products (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id        INTEGER NOT NULL,
            name               TEXT    NOT NULL,
            default_unit       TEXT    NOT NULL DEFAULT 'kg',
            outlet             TEXT    NOT NULL DEFAULT 'restaurant',
            approximate_price  REAL,
            is_active          INTEGER NOT NULL DEFAULT 1,
            sort_order         INTEGER NOT NULL DEFAULT 0,
            created_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at         TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(category_id, name),
            FOREIGN KEY (category_id) REFERENCES store_product_categories(id)
        )
    """)
    product_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_products)").fetchall()
    }
    if "outlet" not in product_cols:
        cursor.execute(
            "ALTER TABLE store_products ADD COLUMN outlet TEXT NOT NULL DEFAULT 'restaurant'"
        )
    if "approximate_price" not in product_cols:
        cursor.execute(
            "ALTER TABLE store_products ADD COLUMN approximate_price REAL"
        )
    for preferred_col in (
        "preferred_supplier_1_id",
        "preferred_supplier_2_id",
        "preferred_supplier_3_id",
    ):
        if preferred_col not in product_cols:
            cursor.execute(
                f"ALTER TABLE store_products ADD COLUMN {preferred_col} INTEGER"
            )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_products_category
        ON store_products(category_id, is_active, sort_order, name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_products_outlet
        ON store_products(outlet, is_active, name)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_products_active_price
        ON store_products(is_active, approximate_price)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_product_variants (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id         INTEGER NOT NULL,
            label              TEXT    NOT NULL,
            qty_in_base        REAL    NOT NULL,
            approximate_price  REAL,
            sort_order         INTEGER NOT NULL DEFAULT 0,
            is_active          INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (product_id) REFERENCES store_products(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_product_variants_product
        ON store_product_variants(product_id, is_active, sort_order, id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_product_variants_active_price
        ON store_product_variants(is_active, approximate_price, product_id)
    """)
    pr_line_cols = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(store_purchase_request_lines)").fetchall()
    }
    if "pack_label" not in pr_line_cols:
        cursor.execute(
            "ALTER TABLE store_purchase_request_lines ADD COLUMN pack_label TEXT NOT NULL DEFAULT ''"
        )
    if "pack_qty_in_base" not in pr_line_cols:
        cursor.execute(
            "ALTER TABLE store_purchase_request_lines ADD COLUMN pack_qty_in_base REAL"
        )
    _seed_store_product_master(cursor)
    _seed_store_product_units(cursor)  # re-run to sync units from seeded products
    cursor.execute(
        "UPDATE store_products SET default_unit = 'liter' WHERE lower(default_unit) = 'ltr'"
    )
    cursor.execute(
        """
        UPDATE store_products
        SET outlet = 'restaurant'
        WHERE outlet IS NULL OR trim(outlet) = ''
           OR lower(outlet) NOT IN ('bar', 'restaurant', 'both')
        """
    )
    # Migrate legacy "kitchen" outlet key → "restaurant" across stores tables.
    for table in (
        "store_indents",
        "store_purchase_requests",
        "store_stock_items",
        "store_stock_movements",
    ):
        cursor.execute(
            f"UPDATE {table} SET outlet = 'restaurant' WHERE lower(outlet) = 'kitchen'"
        )
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_audits (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet       TEXT    NOT NULL,
            place        TEXT    NOT NULL DEFAULT 'warehouse',
            status       TEXT    NOT NULL DEFAULT 'open',
            label        TEXT    NOT NULL DEFAULT '',
            started_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            completed_at TEXT,
            started_by   INTEGER,
            FOREIGN KEY (started_by) REFERENCES users(id)
        )
    """)
    audit_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_stock_audits)").fetchall()
    }
    if "place" not in audit_cols:
        cursor.execute(
            "ALTER TABLE store_stock_audits ADD COLUMN place TEXT NOT NULL DEFAULT 'warehouse'"
        )
        cursor.execute(
            """
            UPDATE store_stock_audits
            SET place = 'warehouse'
            WHERE place IS NULL OR trim(place) = ''
               OR lower(place) NOT IN ('warehouse', 'counter')
            """
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_stock_audits_outlet_status
        ON store_stock_audits(outlet, status, started_at DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_stock_audits_outlet_place_status
        ON store_stock_audits(outlet, place, status, started_at DESC)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS store_stock_audit_lines (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            audit_id       INTEGER NOT NULL,
            stock_item_id  INTEGER,
            item_name      TEXT    NOT NULL,
            unit           TEXT    NOT NULL DEFAULT 'pcs',
            place          TEXT    NOT NULL DEFAULT 'warehouse',
            category_name  TEXT    NOT NULL DEFAULT '',
            system_qty     REAL    NOT NULL DEFAULT 0,
            actual_qty     REAL,
            variance_qty   REAL,
            variance_value REAL,
            status         TEXT    NOT NULL DEFAULT 'pending',
            reason         TEXT    NOT NULL DEFAULT '',
            remarks        TEXT    NOT NULL DEFAULT '',
            unit_cost      REAL,
            verified_at    TEXT,
            verified_by    INTEGER,
            FOREIGN KEY (audit_id) REFERENCES store_stock_audits(id) ON DELETE CASCADE,
            FOREIGN KEY (verified_by) REFERENCES users(id)
        )
    """)
    audit_line_cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_stock_audit_lines)").fetchall()
    }
    if "place" not in audit_line_cols:
        cursor.execute(
            "ALTER TABLE store_stock_audit_lines ADD COLUMN place TEXT NOT NULL DEFAULT 'warehouse'"
        )
        cursor.execute(
            """
            UPDATE store_stock_audit_lines
            SET place = COALESCE((
                SELECT CASE
                    WHEN lower(trim(coalesce(a.place, ''))) IN ('warehouse', 'counter')
                    THEN lower(trim(a.place))
                    ELSE 'warehouse'
                END
                FROM store_stock_audits a
                WHERE a.id = store_stock_audit_lines.audit_id
            ), 'warehouse')
            WHERE place IS NULL OR trim(place) = ''
               OR lower(place) NOT IN ('warehouse', 'counter')
            """
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_store_stock_audit_lines_audit
        ON store_stock_audit_lines(audit_id, status, id)
    """)
    _seed_store_place_demo(cursor, migrated_place=migrated_stock_place)
    conn.commit()


def _store_stock_items_unique_includes_place(cursor) -> bool:
    row = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='store_stock_items'"
    ).fetchone()
    sql = (row[0] or "") if row else ""
    compact = "".join(sql.lower().split())
    return "unique(outlet,place,item_name,unit)" in compact


def _migrate_store_stock_items_place(cursor) -> bool:
    """Rebuild store_stock_items with UNIQUE(outlet, place, item_name, unit).

    Existing on-hand becomes warehouse. Returns True when an old schema was rebuilt.
    """
    cols = {
        row[1] for row in cursor.execute("PRAGMA table_info(store_stock_items)").fetchall()
    }
    if not cols:
        return False
    if "place" in cols and _store_stock_items_unique_includes_place(cursor):
        return False
    cursor.execute(
        """
        CREATE TABLE store_stock_items_new (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            outlet      TEXT    NOT NULL,
            place       TEXT    NOT NULL DEFAULT 'warehouse',
            item_name   TEXT    NOT NULL,
            unit        TEXT    NOT NULL DEFAULT 'pcs',
            qty_on_hand REAL    NOT NULL DEFAULT 0,
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(outlet, place, item_name, unit)
        )
        """
    )
    if "place" in cols:
        cursor.execute(
            """
            INSERT INTO store_stock_items_new
                (id, outlet, place, item_name, unit, qty_on_hand, updated_at)
            SELECT id, outlet,
                   CASE
                     WHEN lower(trim(coalesce(place, ''))) IN ('warehouse', 'counter')
                     THEN lower(trim(place))
                     ELSE 'warehouse'
                   END,
                   item_name, unit, qty_on_hand, updated_at
            FROM store_stock_items
            """
        )
    else:
        cursor.execute(
            """
            INSERT INTO store_stock_items_new
                (id, outlet, place, item_name, unit, qty_on_hand, updated_at)
            SELECT id, outlet, 'warehouse', item_name, unit, qty_on_hand, updated_at
            FROM store_stock_items
            """
        )
    cursor.execute("DROP TABLE store_stock_items")
    cursor.execute("ALTER TABLE store_stock_items_new RENAME TO store_stock_items")
    return True


def _demo_stock_ingredient_lines(cursor, tables: set[str], outlet: str, limit: int = 12):
    """Real Product Master / recipe ingredients for an outlet (no invented names)."""
    lines: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def _add(name, unit):
        item = str(name or "").strip()
        stock_unit = str(unit or "").strip() or "pcs"
        if not item:
            return
        key = (item.lower(), stock_unit.lower())
        if key in seen:
            return
        seen.add(key)
        lines.append((item, stock_unit))

    if "pos_menu_recipe_lines" in tables and "pos_menu_items" in tables:
        for row in cursor.execute(
            """
            SELECT DISTINCT p.name AS name, p.default_unit AS unit
            FROM pos_menu_recipe_lines r
            JOIN store_products p ON p.id = r.product_id
            JOIN pos_menu_items m ON m.id = r.menu_item_id
            WHERE p.is_active = 1
              AND trim(p.name) != ''
              AND (
                lower(coalesce(p.outlet, '')) IN (?, 'both')
                OR lower(coalesce(m.outlet, '')) = ?
              )
            ORDER BY lower(p.name)
            LIMIT ?
            """,
            (outlet, outlet, limit),
        ).fetchall():
            name = row["name"] if hasattr(row, "keys") else row[0]
            unit = row["unit"] if hasattr(row, "keys") else row[1]
            _add(name, unit)
            if len(lines) >= limit:
                return lines
    if len(lines) < limit:
        for row in cursor.execute(
            """
            SELECT name, default_unit AS unit
            FROM store_products
            WHERE is_active = 1
              AND trim(name) != ''
              AND lower(coalesce(outlet, '')) IN (?, 'both')
            ORDER BY sort_order ASC, lower(name)
            LIMIT ?
            """,
            (outlet, limit),
        ).fetchall():
            name = row["name"] if hasattr(row, "keys") else row[0]
            unit = row["unit"] if hasattr(row, "keys") else row[1]
            _add(name, unit)
            if len(lines) >= limit:
                break
    return lines[:limit]


def _seed_store_place_demo(cursor, *, migrated_place: bool) -> None:
    """Guarded warehouse/counter demo stock from the real catalogue.

    Skipped during pytest. Seeds counter (and warehouse when the ledger is empty)
    from Product Master / recipe ingredients only.
    """
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return
    tables = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "store_stock_items" not in tables or "store_products" not in tables:
        return
    product_row = cursor.execute(
        """
        SELECT COUNT(*) AS c FROM store_products
        WHERE is_active = 1 AND trim(name) != ''
        """
    ).fetchone()
    product_count = int((product_row["c"] if hasattr(product_row, "keys") else product_row[0]) or 0)
    if product_count <= 0:
        return
    stock_row = cursor.execute("SELECT COUNT(*) AS c FROM store_stock_items").fetchone()
    stock_count = int((stock_row["c"] if hasattr(stock_row, "keys") else stock_row[0]) or 0)
    counter_row = cursor.execute(
        "SELECT COUNT(*) AS c FROM store_stock_items WHERE lower(place) = 'counter'"
    ).fetchone()
    counter_count = int(
        (counter_row["c"] if hasattr(counter_row, "keys") else counter_row[0]) or 0
    )
    warehouse_row = cursor.execute(
        """
        SELECT COUNT(*) AS c FROM store_stock_items
        WHERE lower(coalesce(place, 'warehouse')) = 'warehouse'
        """
    ).fetchone()
    warehouse_count = int(
        (warehouse_row["c"] if hasattr(warehouse_row, "keys") else warehouse_row[0]) or 0
    )
    seed_empty = stock_count == 0
    seed_counter_on_migrate = migrated_place and warehouse_count > 0 and counter_count == 0
    if not seed_empty and not seed_counter_on_migrate:
        return
    seed_warehouse = seed_empty
    for outlet in ("restaurant", "bar"):
        candidates = _demo_stock_ingredient_lines(cursor, tables, outlet, limit=12)
        for idx, (name, unit) in enumerate(candidates):
            if seed_warehouse:
                cursor.execute(
                    """
                    INSERT OR IGNORE INTO store_stock_items
                        (outlet, place, item_name, unit, qty_on_hand, updated_at)
                    VALUES (?, 'warehouse', ?, ?, ?, datetime('now','localtime'))
                    """,
                    (outlet, name, unit, 12.0 if idx % 2 == 0 else 8.0),
                )
            cursor.execute(
                """
                INSERT OR IGNORE INTO store_stock_items
                    (outlet, place, item_name, unit, qty_on_hand, updated_at)
                VALUES (?, 'counter', ?, ?, ?, datetime('now','localtime'))
                """,
                (outlet, name, unit, 3.0 if idx % 2 == 0 else 1.5),
            )


def _seed_store_product_units(cursor):
    """Seed default product units used on Product Master (idempotent)."""
    defaults = ("kg", "gram", "pcs", "liter", "mL", "bunch", "bottle", "pack")
    for idx, name in enumerate(defaults, start=1):
        cursor.execute(
            """
            INSERT OR IGNORE INTO store_product_units (name, sort_order, is_active)
            VALUES (?, ?, 1)
            """,
            (name, idx * 10),
        )
    # Pull any units already used on products into the master list.
    tables = {
        row[0]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if "store_products" not in tables:
        return
    for row in cursor.execute(
        """
        SELECT DISTINCT default_unit AS name
        FROM store_products
        WHERE default_unit IS NOT NULL AND trim(default_unit) != ''
        """
    ).fetchall():
        unit_name = str(row["name"] if hasattr(row, "keys") else row[0] or "").strip()
        if not unit_name:
            continue
        cursor.execute(
            """
            INSERT OR IGNORE INTO store_product_units (name, sort_order, is_active)
            VALUES (?, ?, 1)
            """,
            (unit_name, 1000),
        )


def _seed_store_product_master(cursor):
    """Seed Hotel Bell Elite daily perishables catalogue (idempotent)."""
    catalog = (
        (
            "Non-Veg",
            10,
            (
                ("T.D. Chicken", "kg"),
                ("Chicken Whole", "kg"),
                ("Staff Chicken", "kg"),
                ("B/L Chicken", "kg"),
                ("Chi-Drumstick", "kg"),
                ("Chi-Lolly Pop", "kg"),
                ("Mutton", "kg"),
                ("B/L Mutton", "kg"),
                ("Prawns", "kg"),
                ("Lobster", "kg"),
                ("Crabs", "kg"),
                ("B/L Fish", "kg"),
                ("Staff Fish", "kg"),
                ("Eggs", "pcs"),
                ("Bread", "pcs"),
            ),
        ),
        (
            "Dairy Products",
            20,
            (
                ("Fresh Paneer", "kg"),
                ("Butter", "kg"),
                ("Vanilla Ice Cream (1 Ltr)", "liter"),
                ("Butter Scotch (1 Ltr)", "liter"),
                ("Strawberry Ice Cream (1 Ltr)", "liter"),
                ("Chocolate Ice Cream (1 Ltr)", "liter"),
                ("Vanilla Ice Cream (4 Ltr)", "liter"),
                ("Butter Scotch (4 Ltr)", "liter"),
                ("Strawberry Ice Cream (4 Ltr)", "liter"),
                ("Chocolate Ice Cream (4 Ltr)", "liter"),
                ("Curd", "kg"),
                ("Coffee Powder 200 gm", "pcs"),
                ("Besan Powder 1 Kg", "kg"),
            ),
        ),
        (
            "Fruits",
            35,
            (
                ("Apple", "kg"),
                ("Anar", "kg"),
                ("Banana", "pcs"),
            ),
        ),
        (
            "Vegetable",
            30,
            (
                ("Arbi", "kg"),
                ("Beet Root", "kg"),
                ("Bitter Gourd", "kg"),
                ("Brinjal", "kg"),
                ("Carrot", "kg"),
                ("Cauliflower", "kg"),
                ("Capsicum", "kg"),
                ("Capsicum R/Y", "kg"),
                ("Cabbage", "kg"),
                ("Coconut", "pcs"),
                ("Cucumber", "kg"),
                ("Curry Leaves", "bunch"),
                ("Drum Stick", "kg"),
                ("French Beans", "kg"),
                ("French Fry", "kg"),
                ("Green Chilly", "kg"),
                ("Ginger", "kg"),
                ("Garlic", "kg"),
                ("Kundru", "kg"),
                ("Long Beans", "kg"),
                ("Lemon", "kg"),
                ("Mint Leaves", "bunch"),
                ("Mooli Bhaji", "kg"),
                ("Pumpkin", "kg"),
                ("Mursa Bhaji", "kg"),
                ("Nali Bhaji", "kg"),
                ("Onion", "kg"),
                ("Potato", "kg"),
                ("Palak Bhaji", "kg"),
                ("Poi Bhaji", "kg"),
                ("Potal", "kg"),
                ("Ridge Gourd", "kg"),
                ("Spring Onion", "kg"),
                ("Snake Gourd", "kg"),
                ("Tomato", "kg"),
                ("Thupi", "kg"),
                ("Coriander Leaves", "bunch"),
                ("Raw Banana", "kg"),
                ("Ladies Finger", "kg"),
                ("Staff Veg.", "kg"),
            ),
        ),
    )
    for cat_name, cat_sort, products in catalog:
        cursor.execute(
            """
            INSERT OR IGNORE INTO store_product_categories (name, sort_order, is_active)
            VALUES (?, ?, 1)
            """,
            (cat_name, cat_sort),
        )
        row = cursor.execute(
            "SELECT id FROM store_product_categories WHERE name = ?",
            (cat_name,),
        ).fetchone()
        if not row:
            continue
        category_id = row["id"] if hasattr(row, "keys") else row[0]
        for idx, (product_name, unit) in enumerate(products, start=1):
            # Prefer a global name match so re-seeds never create Dairy+Fruits twins.
            existing = cursor.execute(
                """
                SELECT id FROM store_products
                WHERE lower(name) = lower(?)
                ORDER BY CASE WHEN is_active = 1 THEN 0 ELSE 1 END, id
                LIMIT 1
                """,
                (product_name,),
            ).fetchone()
            if existing:
                continue
            cursor.execute(
                """
                INSERT INTO store_products
                    (category_id, name, default_unit, outlet, is_active, sort_order)
                VALUES (?, ?, ?, 'restaurant', 1, ?)
                """,
                (category_id, product_name, unit, idx * 10),
            )

    # Move Apple / Anar / Banana onto Fruits and drop duplicate rows.
    fruits_row = cursor.execute(
        "SELECT id FROM store_product_categories WHERE lower(name) = lower('Fruits')"
    ).fetchone()
    if fruits_row:
        fruits_id = fruits_row["id"] if hasattr(fruits_row, "keys") else fruits_row[0]
        for fruit_name in ("Apple", "Anar", "Banana"):
            keep = cursor.execute(
                """
                SELECT id FROM store_products
                WHERE lower(name) = lower(?)
                ORDER BY CASE WHEN is_active = 1 THEN 0 ELSE 1 END, id
                LIMIT 1
                """,
                (fruit_name,),
            ).fetchone()
            if not keep:
                cursor.execute(
                    """
                    INSERT INTO store_products
                        (category_id, name, default_unit, outlet, is_active, sort_order)
                    VALUES (?, ?, ?, 'restaurant', 1, ?)
                    """,
                    (
                        fruits_id,
                        fruit_name,
                        "pcs" if fruit_name == "Banana" else "kg",
                        10,
                    ),
                )
                continue
            keep_id = keep["id"] if hasattr(keep, "keys") else keep[0]
            # Unique(category_id, name) still applies to inactive rows — delete twins.
            cursor.execute(
                """
                DELETE FROM store_product_variants
                WHERE product_id IN (
                    SELECT id FROM store_products
                    WHERE lower(name) = lower(?) AND id != ?
                )
                """,
                (fruit_name, keep_id),
            )
            cursor.execute(
                """
                DELETE FROM store_products
                WHERE lower(name) = lower(?) AND id != ?
                """,
                (fruit_name, keep_id),
            )
            cursor.execute(
                """
                UPDATE store_products
                SET category_id = ?, is_active = 1
                WHERE id = ?
                """,
                (fruits_id, keep_id),
            )


# ---------------------------------------------------------------------------
# Hotel Rooms floor board (front office occupancy — not Sales Update Hotel)
# ---------------------------------------------------------------------------

HOTEL_ROOM_STATUSES = (
    "vacant",
    "occupied",
    "reserved",
    "dirty",
    "out_of_order",
)

HOTEL_ROOM_STATUS_LABELS = {
    "vacant": "Vacant",
    "occupied": "Occupied",
    "reserved": "Reserved",
    "dirty": "Dirty",
    "out_of_order": "Out of order",
}

HOTEL_ROOM_TYPE_LABELS = {
    "premium_without_balcony": "Premium Room",
    "premium_deluxe_balcony": "Deluxe with Balcony",
    "premium_suite_tub": "Suite Room",
}

# Seed inventory from ROOM DETAILS spreadsheet (hardcoded — no Excel at runtime).
_HOTEL_ROOMS_SEED_SPEC = (
    # (room_number, room_type_key)
    ("101", "premium_deluxe_balcony"),
    ("102", "premium_without_balcony"),
    ("103", "premium_deluxe_balcony"),
    ("104", "premium_deluxe_balcony"),
    ("105", "premium_without_balcony"),
    ("106", "premium_deluxe_balcony"),
    ("201", "premium_deluxe_balcony"),
    ("202", "premium_without_balcony"),
    ("203", "premium_deluxe_balcony"),
    ("204", "premium_deluxe_balcony"),
    ("205", "premium_without_balcony"),
    ("206", "premium_deluxe_balcony"),
    ("207", "premium_suite_tub"),
    ("301", "premium_deluxe_balcony"),
    ("302", "premium_without_balcony"),
    ("303", "premium_deluxe_balcony"),
    ("304", "premium_deluxe_balcony"),
    ("305", "premium_without_balcony"),
    ("306", "premium_deluxe_balcony"),
    ("307", "premium_suite_tub"),
)


def ensure_communication_hub_schema(conn):
    """WhatsApp Communication Hub conversations and messages."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_conversations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_e164       TEXT    NOT NULL UNIQUE,
            display_name     TEXT    NOT NULL DEFAULT '',
            last_message_at  TEXT,
            last_preview     TEXT    NOT NULL DEFAULT '',
            unread_count     INTEGER NOT NULL DEFAULT 0,
            created_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at       TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id INTEGER NOT NULL,
            direction       TEXT    NOT NULL,
            message_type    TEXT    NOT NULL DEFAULT 'text',
            body            TEXT    NOT NULL DEFAULT '',
            media_mime      TEXT    NOT NULL DEFAULT '',
            media_filename  TEXT    NOT NULL DEFAULT '',
            media_size      INTEGER NOT NULL DEFAULT 0,
            wa_message_id   TEXT,
            status          TEXT    NOT NULL DEFAULT 'queued',
            error           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            created_by      INTEGER,
            FOREIGN KEY (conversation_id) REFERENCES wa_conversations(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_wa_messages_wa_id
        ON wa_messages(wa_message_id) WHERE wa_message_id IS NOT NULL AND wa_message_id <> ''
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_messages_conversation
        ON wa_messages(conversation_id, created_at, id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_conversations_last
        ON wa_conversations(last_message_at DESC, id DESC)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_conversation_tombstones (
            phone_e164  TEXT PRIMARY KEY,
            deleted_at  TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_promo_campaigns (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            template_name     TEXT    NOT NULL,
            template_language TEXT    NOT NULL DEFAULT '',
            created_by        INTEGER,
            created_at        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            finished_at       TEXT,
            status            TEXT    NOT NULL DEFAULT 'running',
            total_rows        INTEGER NOT NULL DEFAULT 0,
            sent_count        INTEGER NOT NULL DEFAULT 0,
            failed_count      INTEGER NOT NULL DEFAULT 0,
            skipped_count     INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS wa_promo_recipients (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_id  INTEGER NOT NULL,
            row_number   INTEGER NOT NULL DEFAULT 0,
            customer_name TEXT   NOT NULL DEFAULT '',
            phone_e164   TEXT    NOT NULL DEFAULT '',
            status       TEXT    NOT NULL DEFAULT 'pending',
            error        TEXT    NOT NULL DEFAULT '',
            wa_message_id TEXT   NOT NULL DEFAULT '',
            sent_at      TEXT,
            FOREIGN KEY (campaign_id) REFERENCES wa_promo_campaigns(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_wa_promo_recipients_campaign
        ON wa_promo_recipients(campaign_id, id)
        """
    )


def ensure_hotel_rooms_schema(conn):
    """Create singleton hotel_rooms_layout JSON table if missing."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_rooms_layout (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            payload    TEXT    NOT NULL,
            updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_guest_profiles (
            mobile     TEXT PRIMARY KEY,
            profile    TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_room_invoice_seq (
            fiscal_year TEXT PRIMARY KEY,
            last_seq    INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS fb_transfer_invoice_seq (
            fiscal_year TEXT PRIMARY KEY,
            last_seq    INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS room_transfer_invoice_seq (
            fiscal_year TEXT PRIMARY KEY,
            last_seq    INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_settings (
            id         INTEGER PRIMARY KEY CHECK (id = 1),
            payload    TEXT    NOT NULL DEFAULT '{}',
            updated_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    ensure_hotel_room_invoices_schema(conn)
    ensure_hotel_id_documents_schema(conn)


def ensure_hotel_id_documents_schema(conn):
    """Store ID PDFs beside stay metadata so deploys that wipe uploads/ still serve them."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_id_documents (
            stored_name TEXT PRIMARY KEY,
            mime        TEXT NOT NULL DEFAULT 'application/pdf',
            payload     BLOB NOT NULL,
            created_at  TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            owner_user_id INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    cols = {
        row[1]
        for row in conn.execute("PRAGMA table_info(hotel_id_documents)").fetchall()
    }
    if "owner_user_id" not in cols:
        conn.execute(
            "ALTER TABLE hotel_id_documents ADD COLUMN owner_user_id INTEGER NOT NULL DEFAULT 0"
        )


HOTEL_DEFAULT_CGST_PCT = 2.5
HOTEL_DEFAULT_UGST_PCT = 2.5
HOTEL_DEFAULT_CGST_PCT_ABOVE = 9.0
HOTEL_DEFAULT_UGST_PCT_ABOVE = 9.0
HOTEL_DEFAULT_TAX_SLAB_THRESHOLD = 7500.0

HOTEL_DEFAULT_TARIFF_RATES = {
    "premium_without_balcony": 3500.0,
    "premium_deluxe_balcony": 4500.0,
    "premium_suite_tub": 7500.0,
    "extra_mattress": 1000.0,
    "early_checkin": 500.0,
    "late_checkout": 500.0,
    "airport_pickup": 1500.0,
}


def get_hotel_settings(conn):
    """Return hotel settings JSON blob (independent from POS outlet settings)."""
    ensure_hotel_rooms_schema(conn)
    row = conn.execute("SELECT payload FROM hotel_settings WHERE id = 1").fetchone()
    if not row:
        return {}
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    try:
        import asia_tech_client

        if asia_tech_client.ensure_plaintext_secrets_sealed(parsed):
            was_in_tx = bool(getattr(conn, "in_transaction", False))
            blob = json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))
            conn.execute(
                f"""
                INSERT INTO hotel_settings (id, payload, updated_at)
                VALUES (1, ?, {SQL_NOW})
                ON CONFLICT(id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = {SQL_NOW}
                """,
                (blob,),
            )
            if not was_in_tx:
                conn.commit()
    except Exception:
        pass
    return parsed


def save_hotel_settings(conn, settings):
    """Replace hotel settings JSON blob."""
    ensure_hotel_rooms_schema(conn)
    if not isinstance(settings, dict):
        settings = {}
    try:
        import asia_tech_client

        settings = asia_tech_client.seal_settings_secrets(settings)
    except Exception:
        pass
    blob = json.dumps(settings, ensure_ascii=False, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO hotel_settings (id, payload, updated_at)
        VALUES (1, ?, {SQL_NOW})
        ON CONFLICT(id) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """,
        (blob,),
    )
    return settings


def get_hotel_tax_rates(conn):
    """Return CGST/UGST slab fractions (0–1) from Hotel Settings → Taxes."""
    settings = get_hotel_settings(conn)
    values = _pos_settings_panel_values(settings, "taxes")
    cgst_pct = _pos_settings_pct(values, "cgst_pct", 0, HOTEL_DEFAULT_CGST_PCT)
    ugst_pct = _pos_settings_pct(values, "ugst_pct", 1, HOTEL_DEFAULT_UGST_PCT)
    cgst_pct_above = _pos_settings_pct(
        values, "cgst_pct_above", 2, HOTEL_DEFAULT_CGST_PCT_ABOVE
    )
    ugst_pct_above = _pos_settings_pct(
        values, "ugst_pct_above", 3, HOTEL_DEFAULT_UGST_PCT_ABOVE
    )
    threshold = _hotel_settings_money(
        values, "tax_slab_threshold", HOTEL_DEFAULT_TAX_SLAB_THRESHOLD
    )
    return {
        "threshold": threshold,
        "cgst_pct": cgst_pct,
        "ugst_pct": ugst_pct,
        "cgst": round(cgst_pct / 100.0, 6),
        "ugst": round(ugst_pct / 100.0, 6),
        "cgst_pct_above": cgst_pct_above,
        "ugst_pct_above": ugst_pct_above,
        "cgst_above": round(cgst_pct_above / 100.0, 6),
        "ugst_above": round(ugst_pct_above / 100.0, 6),
    }


def hotel_tax_rates_for_tariff(rates, room_rate):
    """Pick CGST/UGST for a tax-inclusive nightly room tariff.

    ``room_rate > threshold`` uses the above-slab rates; ``<=`` uses the
    standard slab. Plain ``{cgst, ugst}`` blobs (no above keys) are returned as-is.
    """
    base = _hotel_tax_rates_or_default(rates)
    cgst_pct = round(float(base["cgst"]) * 100.0, 4)
    ugst_pct = round(float(base["ugst"]) * 100.0, 4)
    if isinstance(rates, dict):
        if rates.get("cgst_pct") is not None:
            try:
                cgst_pct = float(rates["cgst_pct"])
            except (TypeError, ValueError):
                pass
        if rates.get("ugst_pct") is not None:
            try:
                ugst_pct = float(rates["ugst_pct"])
            except (TypeError, ValueError):
                pass
    result = {
        "cgst": base["cgst"],
        "ugst": base["ugst"],
        "cgst_pct": cgst_pct,
        "ugst_pct": ugst_pct,
        "slab": "standard",
    }
    if not isinstance(rates, dict):
        return result
    has_above = any(
        key in rates
        for key in ("cgst_above", "ugst_above", "cgst_pct_above", "ugst_pct_above")
    )
    if not has_above:
        return result
    try:
        threshold = float(rates.get("threshold", HOTEL_DEFAULT_TAX_SLAB_THRESHOLD))
    except (TypeError, ValueError):
        threshold = HOTEL_DEFAULT_TAX_SLAB_THRESHOLD
    if threshold != threshold or threshold < 0:
        threshold = HOTEL_DEFAULT_TAX_SLAB_THRESHOLD
    try:
        tariff = float(room_rate or 0)
    except (TypeError, ValueError):
        tariff = 0.0
    if tariff != tariff or tariff < 0:
        tariff = 0.0
    if tariff <= threshold:
        return result
    try:
        cgst_above = float(rates.get("cgst_above"))
    except (TypeError, ValueError):
        cgst_above = None
    try:
        ugst_above = float(rates.get("ugst_above"))
    except (TypeError, ValueError):
        ugst_above = None
    if cgst_above is None or cgst_above != cgst_above or cgst_above < 0:
        try:
            cgst_pct_above = float(
                rates.get("cgst_pct_above", HOTEL_DEFAULT_CGST_PCT_ABOVE)
            )
        except (TypeError, ValueError):
            cgst_pct_above = HOTEL_DEFAULT_CGST_PCT_ABOVE
        cgst_above = round(cgst_pct_above / 100.0, 6)
    else:
        cgst_pct_above = round(cgst_above * 100.0, 4)
    if ugst_above is None or ugst_above != ugst_above or ugst_above < 0:
        try:
            ugst_pct_above = float(
                rates.get("ugst_pct_above", HOTEL_DEFAULT_UGST_PCT_ABOVE)
            )
        except (TypeError, ValueError):
            ugst_pct_above = HOTEL_DEFAULT_UGST_PCT_ABOVE
        ugst_above = round(ugst_pct_above / 100.0, 6)
    else:
        ugst_pct_above = round(ugst_above * 100.0, 4)
    if rates.get("cgst_pct_above") is not None:
        try:
            cgst_pct_above = float(rates["cgst_pct_above"])
            cgst_above = round(cgst_pct_above / 100.0, 6)
        except (TypeError, ValueError):
            pass
    if rates.get("ugst_pct_above") is not None:
        try:
            ugst_pct_above = float(rates["ugst_pct_above"])
            ugst_above = round(ugst_pct_above / 100.0, 6)
        except (TypeError, ValueError):
            pass
    return {
        "cgst": cgst_above,
        "ugst": ugst_above,
        "cgst_pct": cgst_pct_above,
        "ugst_pct": ugst_pct_above,
        "slab": "above",
    }


def _hotel_stay_tariff_for_tax_slab(stay):
    """Tax-inclusive nightly tariff used to pick the CGST/UGST slab."""
    if not isinstance(stay, dict):
        return 0.0
    try:
        tariff = float(stay.get("roomRate") or stay.get("room_rate") or 0)
    except (TypeError, ValueError):
        tariff = 0.0
    if tariff != tariff or tariff < 0:
        tariff = 0.0
    nightly = stay.get("nightlyRates") or stay.get("nightly_rates") or []
    if isinstance(nightly, list):
        for row in nightly:
            if not isinstance(row, dict):
                continue
            try:
                rate = float(row.get("roomRate") or row.get("room_rate") or 0)
            except (TypeError, ValueError):
                continue
            if rate == rate and rate > tariff:
                tariff = rate
    return round(tariff, 2)


def _hotel_settings_money(values, key, default_amount):
    """Parse a non-negative money amount from settings panel values."""
    if not isinstance(values, dict):
        return float(default_amount)
    field = values.get(key)
    raw = None
    if isinstance(field, dict):
        raw = field.get("value")
    elif field is not None:
        raw = field
    try:
        amount = float(raw)
    except (TypeError, ValueError):
        return float(default_amount)
    if amount != amount or amount < 0:
        return float(default_amount)
    return round(amount, 2)


def get_hotel_tariff_rates(conn):
    """Return default hotel tariffs from Hotel Settings → Tariff."""
    settings = get_hotel_settings(conn)
    values = _pos_settings_panel_values(settings, "tariff")
    defaults = HOTEL_DEFAULT_TARIFF_RATES
    return {
        "premium_without_balcony": _hotel_settings_money(
            values, "rate_premium_without_balcony", defaults["premium_without_balcony"]
        ),
        "premium_deluxe_balcony": _hotel_settings_money(
            values, "rate_premium_deluxe_balcony", defaults["premium_deluxe_balcony"]
        ),
        "premium_suite_tub": _hotel_settings_money(
            values, "rate_premium_suite_tub", defaults["premium_suite_tub"]
        ),
        "extra_mattress": _hotel_settings_money(
            values, "rate_extra_mattress", defaults["extra_mattress"]
        ),
        "early_checkin": _hotel_settings_money(
            values, "rate_early_checkin", defaults["early_checkin"]
        ),
        "late_checkout": _hotel_settings_money(
            values, "rate_late_checkout", defaults["late_checkout"]
        ),
        "airport_pickup": _hotel_settings_money(
            values, "rate_airport_pickup", defaults["airport_pickup"]
        ),
    }


def _hotel_tax_rates_or_default(tax_rates=None):
    if isinstance(tax_rates, dict) and "cgst" in tax_rates and "ugst" in tax_rates:
        try:
            cgst = float(tax_rates["cgst"])
            ugst = float(tax_rates["ugst"])
        except (TypeError, ValueError):
            cgst = HOTEL_DEFAULT_CGST_PCT / 100.0
            ugst = HOTEL_DEFAULT_UGST_PCT / 100.0
        if cgst != cgst or cgst < 0:
            cgst = HOTEL_DEFAULT_CGST_PCT / 100.0
        if ugst != ugst or ugst < 0:
            ugst = HOTEL_DEFAULT_UGST_PCT / 100.0
        return {"cgst": cgst, "ugst": ugst}
    return {
        "cgst": HOTEL_DEFAULT_CGST_PCT / 100.0,
        "ugst": HOTEL_DEFAULT_UGST_PCT / 100.0,
    }


def _hotel_split_inclusive_tax(inclusive_amount, tax_rates=None):
    """Split a tax-inclusive amount into taxable + CGST + UGST.

    Hotel room rates and stay extras are stored inclusive of GST. Returns
    (taxable, cgst, ugst, inclusive) where inclusive == taxable + cgst + ugst.
    """
    rates = _hotel_tax_rates_or_default(tax_rates)
    try:
        inclusive = round(max(0.0, float(inclusive_amount or 0)), 2)
    except (TypeError, ValueError):
        inclusive = 0.0
    factor = 1.0 + float(rates["cgst"]) + float(rates["ugst"])
    if factor <= 0:
        return inclusive, 0.0, 0.0, inclusive
    taxable = round(inclusive / factor, 2)
    cgst = round(taxable * float(rates["cgst"]), 2)
    ugst = round(inclusive - taxable - cgst, 2)
    if ugst < 0:
        ugst = 0.0
        cgst = round(inclusive - taxable, 2)
    return taxable, cgst, ugst, inclusive


HOTEL_INVOICE_SOURCE_HOTEL = "hotel"
HOTEL_INVOICE_SOURCE_POS_TRANSFER = "pos_room_transfer"
HOTEL_INVOICE_SOURCE_FB_COMBINED = "fb_combined_transfer"
_HOTEL_FB_TRANSFER_KINDS = frozenset(
    {"restaurant_room_transfer", "bar_room_transfer"}
)
_HOTEL_INVOICE_STAY_SOURCE_SQL = (
    "COALESCE(NULLIF(TRIM(source), ''), 'hotel') NOT IN "
    "('pos_room_transfer', 'fb_combined_transfer')"
)
_HOTEL_INVOICE_LEDGER_SOURCE_SQL = (
    "COALESCE(NULLIF(TRIM(source), ''), 'hotel') != 'pos_room_transfer'"
)


def ensure_hotel_room_invoices_schema(conn):
    """Archive of generated room stay invoices (survives checkout)."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_room_invoices (
            invoice_number       TEXT PRIMARY KEY,
            room_id              TEXT NOT NULL DEFAULT '',
            room_number          TEXT NOT NULL DEFAULT '',
            room_type_label      TEXT NOT NULL DEFAULT '',
            guest_name           TEXT NOT NULL DEFAULT '',
            booking_number       TEXT NOT NULL DEFAULT '',
            check_in_date        TEXT NOT NULL DEFAULT '',
            check_out_date       TEXT NOT NULL DEFAULT '',
            invoice_generated_at TEXT NOT NULL DEFAULT '',
            estimated_total      REAL NOT NULL DEFAULT 0,
            advance_paid         REAL NOT NULL DEFAULT 0,
            balance_amount       REAL NOT NULL DEFAULT 0,
            status               TEXT NOT NULL DEFAULT 'open',
            source               TEXT NOT NULL DEFAULT 'hotel',
            payload_json         TEXT NOT NULL DEFAULT '{}',
            created_by           TEXT NOT NULL DEFAULT '',
            updated_at           TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(hotel_room_invoices)").fetchall()
    }
    if "source" not in columns:
        conn.execute(
            """
            ALTER TABLE hotel_room_invoices
            ADD COLUMN source TEXT NOT NULL DEFAULT 'hotel'
            """
        )
    if "cancel_reason" not in columns:
        conn.execute(
            """
            ALTER TABLE hotel_room_invoices
            ADD COLUMN cancel_reason TEXT NOT NULL DEFAULT ''
            """
        )
    if "cancelled_at" not in columns:
        conn.execute(
            """
            ALTER TABLE hotel_room_invoices
            ADD COLUMN cancelled_at TEXT NOT NULL DEFAULT ''
            """
        )
    if "created_by" not in columns:
        conn.execute(
            """
            ALTER TABLE hotel_room_invoices
            ADD COLUMN created_by TEXT NOT NULL DEFAULT ''
            """
        )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_room_invoices_generated
        ON hotel_room_invoices(invoice_generated_at DESC)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_room_invoices_status
        ON hotel_room_invoices(status)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_room_invoices_source
        ON hotel_room_invoices(source)
        """
    )
    ensure_hotel_invoice_credits_schema(conn)


def ensure_hotel_invoice_credits_schema(conn):
    """Agency credit receivables created when a hotel invoice is settled as Credit."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_invoice_credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            invoice_number TEXT NOT NULL UNIQUE,
            agency_name TEXT NOT NULL DEFAULT '',
            guest_name TEXT NOT NULL DEFAULT '',
            room_number TEXT NOT NULL DEFAULT '',
            credit_date TEXT NOT NULL DEFAULT '',
            credit_amount REAL NOT NULL DEFAULT 0,
            company TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_invoice_credit_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL DEFAULT '',
            agency_name TEXT NOT NULL DEFAULT '',
            payment_date TEXT NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'cash',
            transaction_id TEXT NOT NULL DEFAULT '',
            total_amount REAL NOT NULL DEFAULT 0,
            notes TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_invoice_credit_payment_allocations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id INTEGER NOT NULL,
            credit_id INTEGER NOT NULL,
            invoice_number TEXT NOT NULL DEFAULT '',
            amount REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_invoice_credits_agency
        ON hotel_invoice_credits(agency_name, credit_date)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_invoice_credit_payments_date
        ON hotel_invoice_credit_payments(payment_date, agency_name)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_invoice_credit_alloc_credit
        ON hotel_invoice_credit_payment_allocations(credit_id)
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_invoice_credit_alloc_payment
        ON hotel_invoice_credit_payment_allocations(payment_id)
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hotel_invoice_credit_payment_mode_splits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            payment_id INTEGER NOT NULL,
            payment_method TEXT NOT NULL DEFAULT 'cash',
            amount REAL NOT NULL DEFAULT 0,
            transaction_id TEXT NOT NULL DEFAULT '',
            receipt_id INTEGER,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hotel_credit_mode_splits_payment
        ON hotel_invoice_credit_payment_mode_splits(payment_id)
        """
    )


def _hotel_invoice_credit_amount_from_stay(stay):
    """Sum of Credit-method payments on a stay (agency receivable)."""
    if not isinstance(stay, dict):
        return 0.0
    total = 0.0
    for raw in stay.get("payments") or []:
        if not isinstance(raw, dict):
            continue
        method = _normalize_hotel_payment_method(
            raw.get("method") or raw.get("paymentMethod") or raw.get("payment_method")
        )
        if method != "credit":
            continue
        try:
            total += round(float(raw.get("amount") or 0), 2)
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def _hotel_invoice_credit_date_from_item(item, stay):
    for raw in (stay.get("payments") or []) if isinstance(stay, dict) else []:
        if not isinstance(raw, dict):
            continue
        method = _normalize_hotel_payment_method(
            raw.get("method") or raw.get("paymentMethod") or raw.get("payment_method")
        )
        if method != "credit":
            continue
        stamp = _hotel_str(raw.get("at") or raw.get("date"), 40)
        if stamp:
            return stamp[:10]
    generated = _hotel_str(item.get("invoice_generated_at"), 40)
    if generated:
        return generated[:10]
    return _hotel_str(item.get("check_out_date"), 10) or date.today().isoformat()


def _hotel_credit_party_id(agency_name):
    """Stable positive int for grouping agencies that are not in Agency Master."""
    key = _normalize_agency_name(agency_name) or str(agency_name or "").strip()
    if not key:
        return 0
    n = 0
    for ch in key.lower():
        n = (n * 31 + ord(ch)) & 0x7FFFFFFF
    return n or 1


def upsert_hotel_invoice_credit(conn, item):
    """Create/update the agency credit receivable for a ledger invoice."""
    ensure_hotel_invoice_credits_schema(conn)
    if not isinstance(item, dict):
        return None
    invoice_number = _hotel_str(item.get("invoice_number"), 60)
    if not invoice_number:
        return None
    room = item.get("room") if isinstance(item.get("room"), dict) else {}
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    credit_amount = _hotel_invoice_credit_amount_from_stay(stay)
    agency_name = _hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160)
    if credit_amount <= 0.009:
        # Invoice archive payloads sometimes omit stay.payments; use live stay / amounts.
        room_id = _hotel_str(item.get("room_id") or room.get("id"), 40)
        live = get_hotel_room(conn, room_id) if room_id else None
        live_stay = live.get("stay") if isinstance(live, dict) else None
        if isinstance(live_stay, dict):
            live_inv = _hotel_str(
                live_stay.get("invoiceNumber") or live_stay.get("invoice_number"), 60
            )
            if not live_inv or live_inv == invoice_number:
                credit_amount = _hotel_invoice_credit_amount_from_stay(live_stay)
                if credit_amount > 0.009:
                    stay = live_stay
                    if not agency_name:
                        agency_name = _hotel_str(
                            live_stay.get("agencyName") or live_stay.get("agency_name"),
                            160,
                        )
        if credit_amount <= 0.009:
            amounts = item.get("payment_amounts")
            if isinstance(amounts, dict):
                try:
                    credit_amount = round(float(amounts.get("credit") or 0), 2)
                except (TypeError, ValueError):
                    credit_amount = 0.0
    if credit_amount <= 0.009:
        return None
    if not agency_name:
        agency_name = _hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160)
    guest_name = _hotel_str(item.get("guest_name") or stay.get("guestName"), 160)
    room_number = _hotel_str(item.get("room_number") or room.get("number"), 80)
    credit_date = _hotel_invoice_credit_date_from_item(item, stay)
    existing = conn.execute(
        "SELECT id FROM hotel_invoice_credits WHERE invoice_number = ?",
        (invoice_number,),
    ).fetchone()
    if existing:
        conn.execute(
            """UPDATE hotel_invoice_credits
               SET agency_name = ?, guest_name = ?, room_number = ?,
                   credit_date = ?, credit_amount = ?,
                   updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (
                agency_name,
                guest_name,
                room_number,
                credit_date,
                credit_amount,
                existing["id"],
            ),
        )
        return int(existing["id"])
    cur = conn.execute(
        """INSERT INTO hotel_invoice_credits
           (invoice_number, agency_name, guest_name, room_number, credit_date, credit_amount, company)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (
            invoice_number,
            agency_name,
            guest_name,
            room_number,
            credit_date,
            credit_amount,
            "",
        ),
    )
    return int(cur.lastrowid)


def sync_hotel_invoice_credit_for_number(conn, invoice_number):
    item = get_hotel_room_invoice(conn, invoice_number)
    if not item:
        return None
    return upsert_hotel_invoice_credit(conn, item)


def sync_hotel_invoice_credits(conn):
    """Backfill receivables from invoices that already have Credit settlements."""
    ensure_hotel_room_invoices_schema(conn)
    rows = conn.execute(
        """
        SELECT invoice_number
        FROM hotel_room_invoices
        WHERE payload_json LIKE '%credit%'
        """
    ).fetchall()
    count = 0
    for row in rows:
        if sync_hotel_invoice_credit_for_number(conn, row["invoice_number"]):
            count += 1
    return count


def hotel_invoice_credit_paid_total(conn, credit_id):
    ensure_hotel_invoice_credits_schema(conn)
    try:
        credit_id = int(credit_id)
    except (TypeError, ValueError):
        return 0.0
    row = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) AS total
           FROM hotel_invoice_credit_payment_allocations
           WHERE credit_id = ?""",
        (credit_id,),
    ).fetchone()
    return round(float(row["total"] or 0), 2) if row else 0.0


_HOTEL_RM_INVOICE_RE = re.compile(r"^HBE/RM/(\d+)/(\d{4}-\d{2})$", re.IGNORECASE)
_HOTEL_HBE_FY_INVOICE_RE = re.compile(r"^HBE/(\d{2}-\d{2})/(\d+)$", re.IGNORECASE)
_HOTEL_FBE_FY_INVOICE_RE = re.compile(r"^FBE/(\d{2}-\d{2})/(\d+)$", re.IGNORECASE)
_HOTEL_INVOICE_PREFIX_FY_RE = re.compile(r"/(\d{2}-\d{2})$", re.IGNORECASE)
HOTEL_INVOICE_SEQ_WIDTH = 5
HOTEL_DEFAULT_INVOICE_PREFIX = "HBE"
HOTEL_DEFAULT_FB_INVOICE_PREFIX = "FBE"
HOTEL_DEFAULT_ROOM_TRANSFER_PREFIX = "RT"
HOTEL_ROOM_PAYMENT_METHODS = ("cash", "upi", "card", "bank_transfer", "credit", "bor")
HOTEL_ROOM_PAYMENT_METHOD_LABELS = {
    "cash": "Cash",
    "upi": "UPI",
    "card": "Card",
    "bank_transfer": "Bank Transfer",
    "credit": "Credit",
    "bor": "Back Office Receipt",
}
HOTEL_LEDGER_PAYMENT_AMOUNT_KEYS = tuple(HOTEL_ROOM_PAYMENT_METHODS)
HOTEL_PAYMENT_AMOUNT_COLUMNS = tuple(
    (key, HOTEL_ROOM_PAYMENT_METHOD_LABELS[key]) for key in HOTEL_LEDGER_PAYMENT_AMOUNT_KEYS
)


def _empty_hotel_payment_amounts():
    """Zeroed tender map for hotel invoice ledger settlement columns."""
    return {key: 0.0 for key in HOTEL_LEDGER_PAYMENT_AMOUNT_KEYS}


def _hotel_payment_amounts_from_payments(rows):
    """Sum payment amounts by normalized hotel tender method."""
    amounts = _empty_hotel_payment_amounts()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        try:
            amount = float(row.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if abs(amount) < 0.005:
            continue
        key = _normalize_hotel_payment_method(
            row.get("method") or row.get("payment_method") or row.get("paymentMethod")
        )
        if not key or key not in amounts:
            continue
        amounts[key] = round(amounts[key] + amount, 2)
    return amounts


def _normalize_hotel_invoice_prefix(prefix, default=HOTEL_DEFAULT_INVOICE_PREFIX):
    """Trim and strip trailing slashes; fall back to default when empty."""
    text = str(prefix or "").strip()
    while text.endswith("/"):
        text = text[:-1].rstrip()
    return text or str(default or HOTEL_DEFAULT_INVOICE_PREFIX)


def _hotel_settings_invoice_prefix_value(conn, key, default):
    """Read a text prefix from Hotel Settings → Invoice panel."""
    settings = get_hotel_settings(conn)
    values = _pos_settings_panel_values(settings, "invoice")
    field = values.get(key) if isinstance(values, dict) else None
    raw = None
    if isinstance(field, dict):
        raw = field.get("value")
    elif field is not None:
        raw = field
    return _normalize_hotel_invoice_prefix(raw, default)


def hotel_room_invoice_prefix(conn):
    """Invoice series stem from Hotel Settings → Invoice → Hotel Invoice Prefix."""
    return _hotel_settings_invoice_prefix_value(
        conn, "invoice_prefix", HOTEL_DEFAULT_INVOICE_PREFIX
    )


def hotel_fb_invoice_prefix(conn):
    """Series stem for F&B room-transfer invoices (Hotel Settings → Invoice → F&B Room Transfer)."""
    return _hotel_settings_invoice_prefix_value(
        conn, "fb_invoice_prefix", HOTEL_DEFAULT_FB_INVOICE_PREFIX
    )


def hotel_room_transfer_invoice_prefix(conn):
    """Series stem for per-order room-transfer ledger rows (default RT)."""
    return _hotel_settings_invoice_prefix_value(
        conn, "room_transfer_prefix", HOTEL_DEFAULT_ROOM_TRANSFER_PREFIX
    )


def _hotel_invoice_prefix_embedded_fy(prefix, default=HOTEL_DEFAULT_INVOICE_PREFIX):
    """Return yy-yy when prefix already ends with a fiscal year segment, else None."""
    stem = _normalize_hotel_invoice_prefix(prefix, default)
    match = _HOTEL_INVOICE_PREFIX_FY_RE.search(stem)
    if not match:
        return None
    return match.group(1)


def format_hotel_room_invoice_number(
    prefix, short_fy, seq, default=HOTEL_DEFAULT_INVOICE_PREFIX
):
    """Build invoice number from settings prefix + FY + zero-padded seq."""
    stem = _normalize_hotel_invoice_prefix(prefix, default)
    try:
        seq_n = int(seq)
    except (TypeError, ValueError):
        seq_n = 0
    seq_s = f"{seq_n:0{HOTEL_INVOICE_SEQ_WIDTH}d}"
    if _hotel_invoice_prefix_embedded_fy(stem, default):
        return f"{stem}/{seq_s}"
    fy = str(short_fy or "").strip() or indian_fiscal_year_short_label()
    return f"{stem}/{fy}/{seq_s}"


def _hotel_room_invoice_seq_from_number(
    invoice_number, prefix, short_fy, default=HOTEL_DEFAULT_INVOICE_PREFIX
):
    """Return sequence int from a number matching the active prefix series, else None."""
    number = str(invoice_number or "").strip()
    if not number:
        return None
    stem = _normalize_hotel_invoice_prefix(prefix, default)
    embedded = _hotel_invoice_prefix_embedded_fy(stem, default)
    if embedded:
        pattern = re.compile(
            r"^" + re.escape(stem) + r"/(\d+)$",
            re.IGNORECASE,
        )
        match = pattern.match(number)
        if not match:
            return None
        # Only count against the FY encoded in the prefix when it matches the active FY.
        if embedded.lower() != str(short_fy or "").strip().lower():
            return None
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return None
    pattern = re.compile(
        r"^" + re.escape(stem) + r"/(\d{2}-\d{2})/(\d+)$",
        re.IGNORECASE,
    )
    match = pattern.match(number)
    if not match:
        return None
    if match.group(1).lower() != str(short_fy or "").strip().lower():
        return None
    try:
        return int(match.group(2))
    except (TypeError, ValueError):
        return None


def _hotel_hbe_fy_seq_from_number(invoice_number, short_fy):
    """Return the integer sequence from HBE/{yy-yy}/{n}, else None."""
    return _hotel_room_invoice_seq_from_number(
        invoice_number, HOTEL_DEFAULT_INVOICE_PREFIX, short_fy
    )


def _max_hotel_room_invoice_seq(
    conn, prefix, short_fy, default=HOTEL_DEFAULT_INVOICE_PREFIX
):
    """Highest seq already used for this prefix + FY on ledger rows or live stays."""
    stem = _normalize_hotel_invoice_prefix(prefix, default)
    fy = str(short_fy or "").strip()
    embedded = _hotel_invoice_prefix_embedded_fy(stem, default)
    if embedded:
        like = f"{stem}/%"
    else:
        like = f"{stem}/{fy}/%"
    used_max = 0
    rows = conn.execute(
        """
        SELECT invoice_number
        FROM hotel_room_invoices
        WHERE upper(invoice_number) LIKE upper(?)
        """,
        (like,),
    ).fetchall()
    for row in rows:
        seq = _hotel_room_invoice_seq_from_number(
            row["invoice_number"], stem, fy, default=default
        )
        if seq and seq > used_max:
            used_max = seq
    try:
        rooms = get_hotel_rooms_layout(conn).get("rooms") or []
    except Exception:
        rooms = []
    for room in rooms:
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
        upcoming = (
            room.get("upcomingStay")
            if isinstance(room.get("upcomingStay"), dict)
            else {}
        )
        for blob in (stay, upcoming):
            for key in (
                "invoiceNumber",
                "invoice_number",
                "fbTransferInvoiceNumber",
                "fb_transfer_invoice_number",
            ):
                seq = _hotel_room_invoice_seq_from_number(
                    blob.get(key), stem, fy, default=default
                )
                if seq and seq > used_max:
                    used_max = seq
    return used_max


def _max_hotel_hbe_fy_seq(conn, short_fy):
    """Highest HBE/{yy-yy}/{n} already used on ledger rows or live stays."""
    return _max_hotel_room_invoice_seq(conn, HOTEL_DEFAULT_INVOICE_PREFIX, short_fy)


def _sqlite_begin_immediate(conn):
    """Take a reserved write lock so concurrent invoice seq allocators serialize.

    No-op when this connection is already inside a transaction (cannot nest BEGIN).
    """
    try:
        if conn.in_transaction:
            return
    except Exception:
        pass
    try:
        conn.execute("BEGIN IMMEDIATE")
    except sqlite3.OperationalError:
        pass


_INVOICE_SEQ_TABLES = frozenset(
    {
        "hotel_room_invoice_seq",
        "fb_transfer_invoice_seq",
        "room_transfer_invoice_seq",
    }
)


def _bump_named_invoice_seq(conn, table, fiscal_year, scanned):
    """Atomically set last_seq = max(stored, scanned)+1 for one FY row."""
    if table not in _INVOICE_SEQ_TABLES:
        raise ValueError("unknown invoice sequence table")
    fy = str(fiscal_year or "").strip()
    scanned_n = int(scanned or 0)
    conn.execute(
        f"INSERT OR IGNORE INTO {table} (fiscal_year, last_seq) VALUES (?, 0)",
        (fy,),
    )
    conn.execute(
        f"""
        UPDATE {table}
        SET last_seq = MAX(last_seq, ?) + 1
        WHERE fiscal_year = ?
        """,
        (scanned_n, fy),
    )
    row = conn.execute(
        f"SELECT last_seq FROM {table} WHERE fiscal_year = ?",
        (fy,),
    ).fetchone()
    return int(row["last_seq"] or 1) if row else scanned_n + 1


def next_hotel_room_invoice_seq(conn, fiscal_year, prefix=None):
    """Next sequence for the active hotel invoice prefix + Indian fiscal year."""
    ensure_hotel_rooms_schema(conn)
    _sqlite_begin_immediate(conn)
    stem = (
        _normalize_hotel_invoice_prefix(prefix)
        if prefix is not None
        else hotel_room_invoice_prefix(conn)
    )
    fy = str(fiscal_year or "").strip()
    if not fy:
        fy = indian_fiscal_year_label()
    short_fy = _hotel_invoice_prefix_embedded_fy(stem) or indian_fiscal_year_short_label(
        fy
    )
    scanned = _max_hotel_room_invoice_seq(conn, stem, short_fy)
    return _bump_named_invoice_seq(conn, "hotel_room_invoice_seq", short_fy, scanned)


def allocate_hotel_room_invoice_number(conn, when=None):
    """Allocate {prefix}/{yy-yy}/{n} (or series-root/{n}) for a room stay invoice."""
    prefix = hotel_room_invoice_prefix(conn)
    fy = indian_fiscal_year_label(when)
    short_fy = _hotel_invoice_prefix_embedded_fy(prefix) or indian_fiscal_year_short_label(
        fy
    )
    seq = next_hotel_room_invoice_seq(conn, fy, prefix=prefix)
    return format_hotel_room_invoice_number(prefix, short_fy, seq)


def _hotel_fbe_fy_seq_from_number(invoice_number, short_fy, prefix=None):
    """Return the integer sequence from FBE/{yy-yy}/{n} (or custom prefix), else None."""
    stem = _normalize_hotel_invoice_prefix(
        prefix, HOTEL_DEFAULT_FB_INVOICE_PREFIX
    )
    return _hotel_room_invoice_seq_from_number(
        invoice_number,
        stem,
        short_fy,
        default=HOTEL_DEFAULT_FB_INVOICE_PREFIX,
    )


def _max_hotel_fbe_fy_seq(conn, short_fy, prefix=None):
    """Highest F&B transfer invoice seq already used on ledger rows or live stays."""
    stem = (
        _normalize_hotel_invoice_prefix(prefix, HOTEL_DEFAULT_FB_INVOICE_PREFIX)
        if prefix is not None
        else hotel_fb_invoice_prefix(conn)
    )
    return _max_hotel_room_invoice_seq(
        conn, stem, short_fy, default=HOTEL_DEFAULT_FB_INVOICE_PREFIX
    )


def next_fb_transfer_invoice_seq(conn, fiscal_year, prefix=None):
    """Next F&B transfer invoice sequence for the given Indian fiscal year."""
    ensure_hotel_rooms_schema(conn)
    _sqlite_begin_immediate(conn)
    stem = (
        _normalize_hotel_invoice_prefix(prefix, HOTEL_DEFAULT_FB_INVOICE_PREFIX)
        if prefix is not None
        else hotel_fb_invoice_prefix(conn)
    )
    fy = str(fiscal_year or "").strip()
    if not fy:
        fy = indian_fiscal_year_label()
    short_fy = _hotel_invoice_prefix_embedded_fy(
        stem, HOTEL_DEFAULT_FB_INVOICE_PREFIX
    ) or indian_fiscal_year_short_label(fy)
    scanned = _max_hotel_fbe_fy_seq(conn, short_fy, prefix=stem)
    return _bump_named_invoice_seq(conn, "fb_transfer_invoice_seq", short_fy, scanned)


def allocate_fb_transfer_invoice_number(conn, when=None):
    """Allocate {fb_prefix}/{yy-yy}/{n} for a combined restaurant+bar room-transfer invoice."""
    prefix = hotel_fb_invoice_prefix(conn)
    fy = indian_fiscal_year_label(when)
    short_fy = _hotel_invoice_prefix_embedded_fy(
        prefix, HOTEL_DEFAULT_FB_INVOICE_PREFIX
    ) or indian_fiscal_year_short_label(fy)
    seq = next_fb_transfer_invoice_seq(conn, fy, prefix=prefix)
    return format_hotel_room_invoice_number(
        prefix, short_fy, seq, default=HOTEL_DEFAULT_FB_INVOICE_PREFIX
    )


def next_room_transfer_invoice_seq(conn, fiscal_year, prefix=None):
    """Next per-order room-transfer ledger sequence for the given fiscal year."""
    ensure_hotel_rooms_schema(conn)
    _sqlite_begin_immediate(conn)
    stem = (
        _normalize_hotel_invoice_prefix(prefix, HOTEL_DEFAULT_ROOM_TRANSFER_PREFIX)
        if prefix is not None
        else hotel_room_transfer_invoice_prefix(conn)
    )
    fy = str(fiscal_year or "").strip()
    if not fy:
        fy = indian_fiscal_year_label()
    short_fy = _hotel_invoice_prefix_embedded_fy(
        stem, HOTEL_DEFAULT_ROOM_TRANSFER_PREFIX
    ) or indian_fiscal_year_short_label(fy)
    scanned = _max_hotel_room_invoice_seq(
        conn, stem, short_fy, default=HOTEL_DEFAULT_ROOM_TRANSFER_PREFIX
    )
    return _bump_named_invoice_seq(conn, "room_transfer_invoice_seq", short_fy, scanned)


def allocate_room_transfer_invoice_number(conn, when=None):
    """Allocate {rt_prefix}/{yy-yy}/{n} for a POS room-transfer ledger row."""
    prefix = hotel_room_transfer_invoice_prefix(conn)
    fy = indian_fiscal_year_label(when)
    short_fy = _hotel_invoice_prefix_embedded_fy(
        prefix, HOTEL_DEFAULT_ROOM_TRANSFER_PREFIX
    ) or indian_fiscal_year_short_label(fy)
    seq = next_room_transfer_invoice_seq(conn, fy, prefix=prefix)
    return format_hotel_room_invoice_number(
        prefix, short_fy, seq, default=HOTEL_DEFAULT_ROOM_TRANSFER_PREFIX
    )


def _pos_room_transfer_ledger_invoice_number(conn, order_no):
    """Ledger invoice_number for a POS room-transfer order (legacy or RT series)."""
    needle = str(order_no or "").strip()
    if not needle:
        return None
    ensure_hotel_room_invoices_schema(conn)
    row = conn.execute(
        """
        SELECT invoice_number
        FROM hotel_room_invoices
        WHERE source = ?
          AND (
            invoice_number = ?
            OR lower(trim(COALESCE(json_extract(payload_json, '$.posOrderNo'), '')))
               = lower(?)
          )
        LIMIT 1
        """,
        (HOTEL_INVOICE_SOURCE_POS_TRANSFER, needle, needle),
    ).fetchone()
    if not row:
        return None
    return str(row["invoice_number"] or "").strip() or None


def _hotel_folio_is_fb_transfer(line):
    kind = str((line or {}).get("kind") or "").strip().lower()
    return kind in _HOTEL_FB_TRANSFER_KINDS


def _hotel_fb_transfer_lines(stay):
    folio = (stay or {}).get("folioCharges") or (stay or {}).get("folio_charges") or []
    if not isinstance(folio, list):
        return []
    return [dict(line) for line in folio if isinstance(line, dict) and _hotel_folio_is_fb_transfer(line)]


def _hotel_hotel_folio_lines(stay):
    folio = (stay or {}).get("folioCharges") or (stay or {}).get("folio_charges") or []
    if not isinstance(folio, list):
        return []
    return [
        dict(line)
        for line in folio
        if isinstance(line, dict) and not _hotel_folio_is_fb_transfer(line)
    ]


def _hotel_fb_transfer_total(stay):
    return round(
        sum(float(line.get("amount") or 0) for line in _hotel_fb_transfer_lines(stay)),
        2,
    )


def _hotel_fb_transfer_unsettled_total(stay):
    total = 0.0
    for line in _hotel_fb_transfer_lines(stay):
        if line.get("settled"):
            continue
        total += float(line.get("amount") or 0)
    return round(total, 2)


def _hotel_combined_checkout_balance(stay):
    hotel_bal = round(float((stay or {}).get("balanceAmount") or 0), 2)
    fb_bal = round(float((stay or {}).get("fbTransferBalance") or 0), 2)
    return round(hotel_bal + fb_bal, 2)


def _hotel_folio_line_invoiced_no(line):
    if not isinstance(line, dict):
        return ""
    return _hotel_str(
        line.get("invoicedInvoiceNumber") or line.get("invoiced_invoice_number"), 60
    )


def _hotel_invoice_history_raw(stay):
    raw = (stay or {}).get("invoiceHistory") or (stay or {}).get("invoice_history") or []
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _hotel_invoice_history_entries(stay, kind=None):
    entries = []
    seen = set()
    for item in _hotel_invoice_history_raw(stay):
        inv = _hotel_str(item.get("invoiceNumber") or item.get("invoice_number"), 60)
        entry_kind = _hotel_str(item.get("kind"), 10).lower()
        if not inv or inv in seen:
            continue
        if kind and entry_kind != kind:
            continue
        seen.add(inv)
        entries.append(
            {
                "kind": entry_kind or "hotel",
                "invoiceNumber": inv,
                "generatedAt": _hotel_str(
                    item.get("generatedAt") or item.get("generated_at"), 40
                ),
                "estimatedTotal": round(float(item.get("estimatedTotal") or 0), 2),
                "balanceAmount": round(float(item.get("balanceAmount") or 0), 2),
                "billableNights": max(
                    0, int(_hotel_num(item.get("billableNights") or item.get("billable_nights"), 0))
                ),
                "folioLineIds": [
                    _hotel_str(x, 40)
                    for x in (item.get("folioLineIds") or item.get("folio_line_ids") or [])
                    if _hotel_str(x, 40)
                ],
                "snapshotStay": item.get("snapshotStay")
                if isinstance(item.get("snapshotStay"), dict)
                else None,
            }
        )
    if kind == "hotel" or kind is None:
        primary = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
        if primary and primary not in seen:
            entries.insert(
                0,
                {
                    "kind": "hotel",
                    "invoiceNumber": primary,
                    "generatedAt": _hotel_str(
                        stay.get("invoiceGeneratedAt") or stay.get("invoice_generated_at"), 40
                    ),
                    "estimatedTotal": round(
                        float(stay.get("hotelInvoicedEstimatedTotal") or stay.get("estimatedTotal") or 0),
                        2,
                    ),
                    "balanceAmount": round(float(stay.get("balanceAmount") or 0), 2),
                    "billableNights": max(
                        0,
                        int(
                            _hotel_num(
                                stay.get("hotelInvoicedBillableNights")
                                or stay.get("billableNights"),
                                0,
                            )
                        ),
                    ),
                    "folioLineIds": [],
                    "snapshotStay": None,
                },
            )
    if kind == "fb" or kind is None:
        primary_fb = _hotel_str(
            stay.get("fbTransferInvoiceNumber") or stay.get("fb_transfer_invoice_number"), 60
        )
        if primary_fb and primary_fb not in {e["invoiceNumber"] for e in entries}:
            fb_lines = [
                l
                for l in _hotel_fb_transfer_lines(stay)
                if _hotel_folio_line_invoiced_no(l) == primary_fb
                or (
                    not _hotel_folio_line_invoiced_no(l)
                    and not any(
                        _hotel_folio_line_invoiced_no(x)
                        for x in _hotel_fb_transfer_lines(stay)
                    )
                )
            ]
            if not fb_lines:
                fb_lines = _hotel_fb_transfer_lines(stay)
            fb_total = round(
                sum(float(l.get("amount") or 0) for l in fb_lines), 2
            )
            entries.append(
                {
                    "kind": "fb",
                    "invoiceNumber": primary_fb,
                    "generatedAt": _hotel_str(
                        stay.get("fbTransferInvoiceGeneratedAt")
                        or stay.get("fb_transfer_invoice_generated_at"),
                        40,
                    ),
                    "estimatedTotal": fb_total,
                    "balanceAmount": round(float(stay.get("fbTransferBalance") or 0), 2),
                    "billableNights": 0,
                    "folioLineIds": [
                        _hotel_str(l.get("id"), 40) for l in fb_lines if _hotel_str(l.get("id"), 40)
                    ],
                    "snapshotStay": None,
                }
            )
    return entries


def _hotel_append_invoice_history(stay, entry):
    if not isinstance(stay, dict) or not isinstance(entry, dict):
        return
    history = _hotel_invoice_history_raw(stay)
    inv = _hotel_str(entry.get("invoiceNumber"), 60)
    if not inv:
        return
    history = [h for h in history if _hotel_str(h.get("invoiceNumber"), 60) != inv]
    history.append(entry)
    stay["invoiceHistory"] = history[-50:]


def _hotel_pending_fb_transfer_lines(stay):
    lines = []
    for line in _hotel_fb_transfer_lines(stay):
        if _hotel_folio_line_invoiced_no(line):
            continue
        lines.append(line)
    return lines


def _hotel_pending_fb_total(stay):
    return round(
        sum(float(line.get("amount") or 0) for line in _hotel_pending_fb_transfer_lines(stay)),
        2,
    )


def _hotel_pending_hotel_amount(stay):
    """Return (pending_total, breakdown_lines) for uninvoiced hotel charges."""
    if not isinstance(stay, dict):
        return 0.0, []
    primary = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    if not primary:
        return round(float(stay.get("estimatedTotal") or 0), 2), []

    current_nights = max(1, int(_hotel_num(stay.get("billableNights"), 1)))
    raw_invoiced = int(_hotel_num(stay.get("hotelInvoicedBillableNights"), 0))
    # Missing/zero night snapshot → treat nights as already invoiced (legacy stays).
    invoiced_nights = raw_invoiced if raw_invoiced > 0 else current_nights
    has_hotel_snap = bool(
        raw_invoiced > 0
        or float(stay.get("hotelInvoicedEstimatedTotal") or 0) > 0.009
        or float(stay.get("hotelInvoicedExtraBedAmount") or 0) > 0.009
        or float(stay.get("hotelInvoicedEarlyCheckinAmount") or 0) > 0.009
        or float(stay.get("hotelInvoicedLateCheckoutAmount") or 0) > 0.009
    )
    pending = 0.0
    breakdown = []

    if current_nights > invoiced_nights:
        full_room = _hotel_stay_room_charges_amount(stay, current_nights)
        locked_room = _hotel_stay_room_charges_amount(stay, invoiced_nights)
        delta = round(full_room - locked_room, 2)
        if delta > 0.009:
            pending += delta
            extra_nights = current_nights - invoiced_nights
            breakdown.append(
                {
                    "label": f"Overstay ({extra_nights} night{'s' if extra_nights != 1 else ''})",
                    "amount": delta,
                }
            )

    snap_fields = (
        ("extraBedAmount", "hotelInvoicedExtraBedAmount", "Extra bed"),
        ("earlyCheckinAmount", "hotelInvoicedEarlyCheckinAmount", "Early check-in"),
        ("lateCheckoutAmount", "hotelInvoicedLateCheckoutAmount", "Late checkout"),
    )
    for field, snap_field, label in snap_fields:
        current = round(float(stay.get(field) or 0), 2)
        if has_hotel_snap:
            snap = round(float(stay.get(snap_field) or 0), 2)
        else:
            # Legacy invoice without snapshots — do not invent pending extras.
            snap = current
        delta = round(current - snap, 2)
        if delta > 0.009:
            pending += delta
            breakdown.append({"label": label, "amount": delta})

    for line in _hotel_hotel_folio_lines(stay):
        if _hotel_folio_line_invoiced_no(line):
            continue
        amt = round(float(line.get("amount") or 0), 2)
        if amt <= 0:
            continue
        # Untagged folio on a legacy invoiced stay was almost always billed already.
        if not has_hotel_snap:
            continue
        pending += amt
        breakdown.append(
            {"label": _hotel_str(line.get("label"), 120) or "Other charge", "amount": amt}
        )

    return round(pending, 2), breakdown


def _hotel_has_pending_charges(stay):
    pending_hotel, _ = _hotel_pending_hotel_amount(stay)
    pending_fb = _hotel_pending_fb_total(stay)
    return pending_hotel > 0.009 or pending_fb > 0.009


def _hotel_tag_folio_lines(stay, invoice_number, predicate):
    invoice_number = _hotel_str(invoice_number, 60)
    if not invoice_number or not isinstance(stay, dict):
        return []
    tagged_ids = []
    folio = []
    for line in stay.get("folioCharges") or []:
        if not isinstance(line, dict):
            continue
        row = dict(line)
        if predicate(row) and not _hotel_folio_line_invoiced_no(row):
            row["invoicedInvoiceNumber"] = invoice_number
            lid = _hotel_str(row.get("id"), 40)
            if lid:
                tagged_ids.append(lid)
        folio.append(row)
    stay["folioCharges"] = folio
    return tagged_ids


def _hotel_allocate_hotel_invoice_balances(stay):
    """FIFO hotel balance across minted HBE rows (oldest first)."""
    entries = [e for e in _hotel_invoice_history_entries(stay, kind="hotel") if e.get("invoiceNumber")]
    remaining = round(float(stay.get("balanceAmount") or 0), 2)
    out = {}
    for entry in entries:
        inv = entry["invoiceNumber"]
        cap = round(float(entry.get("estimatedTotal") or 0), 2)
        if cap <= 0:
            out[inv] = 0.0
            continue
        share = round(min(cap, max(0.0, remaining)), 2)
        out[inv] = share
        remaining = round(max(0.0, remaining - share), 2)
    return out


def _hotel_allocate_fb_invoice_balances(stay):
    entries = [e for e in _hotel_invoice_history_entries(stay, kind="fb") if e.get("invoiceNumber")]
    remaining = round(float(stay.get("fbTransferBalance") or 0), 2)
    out = {}
    for entry in entries:
        inv = entry["invoiceNumber"]
        lines = [
            l
            for l in _hotel_fb_transfer_lines(stay)
            if _hotel_folio_line_invoiced_no(l) == inv and not l.get("settled")
        ]
        cap = round(sum(float(l.get("amount") or 0) for l in lines), 2)
        share = round(min(cap, max(0.0, remaining)), 2)
        out[inv] = share
        remaining = round(max(0.0, remaining - share), 2)
    return out


def _hotel_backfill_invoice_lock_fields(stay):
    """Tag legacy folio lines and snapshots after first invoice (pre-lock data)."""
    if not isinstance(stay, dict):
        return stay
    hbe = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    fbe = _hotel_str(
        stay.get("fbTransferInvoiceNumber") or stay.get("fb_transfer_invoice_number"), 60
    )
    if hbe and not stay.get("hotelInvoicedBillableNights"):
        stay["hotelInvoicedBillableNights"] = max(
            1, int(_hotel_num(stay.get("billableNights"), 1))
        )
        stay["hotelInvoicedEstimatedTotal"] = round(float(stay.get("estimatedTotal") or 0), 2)
        stay["hotelInvoicedExtraBedAmount"] = round(float(stay.get("extraBedAmount") or 0), 2)
        stay["hotelInvoicedEarlyCheckinAmount"] = round(
            float(stay.get("earlyCheckinAmount") or 0), 2
        )
        stay["hotelInvoicedLateCheckoutAmount"] = round(
            float(stay.get("lateCheckoutAmount") or 0), 2
        )
        _hotel_tag_folio_lines(stay, hbe, lambda line: not _hotel_folio_is_fb_transfer(line))
    if fbe:
        fb_lines = _hotel_fb_transfer_lines(stay)
        if fb_lines and not any(_hotel_folio_line_invoiced_no(l) for l in fb_lines):
            _hotel_tag_folio_lines(stay, fbe, _hotel_folio_is_fb_transfer)
    return stay


def _hotel_build_hotel_invoice_snapshot_stay(stay, invoice_number, estimated_total, folio_lines=None):
    snap = dict(stay)
    snap["invoiceNumber"] = invoice_number
    snap["invoiceGenerated"] = True
    snap["estimatedTotal"] = round(float(estimated_total or 0), 2)
    snap["balanceAmount"] = round(float(estimated_total or 0), 2)
    if folio_lines is not None:
        hotel_folio = [
            dict(line)
            for line in (folio_lines or [])
            if isinstance(line, dict) and not _hotel_folio_is_fb_transfer(line)
        ]
        fb_folio = [
            dict(line)
            for line in (stay.get("folioCharges") or [])
            if isinstance(line, dict) and _hotel_folio_is_fb_transfer(line)
        ]
        snap["folioCharges"] = hotel_folio + fb_folio
    return snap


def _hotel_build_fb_invoice_snapshot_stay(stay, invoice_number, transfer_lines, generated_at=""):
    snap = dict(stay)
    snap["folioCharges"] = [dict(line) for line in (transfer_lines or [])]
    snap["invoiceNumber"] = invoice_number
    snap["fbTransferInvoiceNumber"] = invoice_number
    snap["invoiceGenerated"] = True
    snap["invoiceGeneratedAt"] = generated_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    snap["fbTransferInvoiceGeneratedAt"] = snap["invoiceGeneratedAt"]
    snap["fbTransferInvoiceGenerated"] = True
    fb_total = round(sum(float(l.get("amount") or 0) for l in transfer_lines or []), 2)
    snap["estimatedTotal"] = fb_total
    snap["balanceAmount"] = fb_total
    snap["fbTransferTotal"] = fb_total
    inv_no = _hotel_str(invoice_number, 60)
    scoped_payments = []
    for pay in stay.get("fbTransferPayments") or []:
        if not isinstance(pay, dict):
            continue
        pay_inv = _hotel_str(pay.get("invoiceNumber") or pay.get("invoice_number"), 60)
        if pay_inv and inv_no and pay_inv != inv_no:
            continue
        scoped_payments.append(dict(pay))
    snap["fbTransferPayments"] = scoped_payments
    return snap


def _hotel_get_invoice_ledger_row(conn, invoice_number):
    ensure_hotel_room_invoices_schema(conn)
    return conn.execute(
        """
        SELECT invoice_number, status, payload_json, estimated_total, advance_paid,
               balance_amount, invoice_generated_at, room_number
        FROM hotel_room_invoices
        WHERE invoice_number = ?
        """,
        (_hotel_str(invoice_number, 60),),
    ).fetchone()


def _hotel_merge_live_payments_into_payload(existing_payload, stay):
    if not isinstance(existing_payload, dict):
        existing_payload = {}
    payload = dict(existing_payload)
    payload_stay = dict(payload.get("stay") or {})
    if isinstance(stay, dict):
        for key in (
            "payments",
            "advancePaid",
            "balanceAmount",
            "combinedBalanceDue",
            "fbTransferBalance",
            "invoiceEditOpen",
            "invoiceGenerated",
        ):
            if key in stay:
                payload_stay[key] = stay.get(key)
        inv_no = _hotel_str(
            payload_stay.get("fbTransferInvoiceNumber")
            or payload_stay.get("invoiceNumber")
            or stay.get("fbTransferInvoiceNumber"),
            60,
        )
        scoped_fb_payments = []
        for pay in stay.get("fbTransferPayments") or []:
            if not isinstance(pay, dict):
                continue
            pay_inv = _hotel_str(pay.get("invoiceNumber") or pay.get("invoice_number"), 60)
            if pay_inv and inv_no and pay_inv != inv_no:
                continue
            scoped_fb_payments.append(dict(pay))
        payload_stay["fbTransferPayments"] = scoped_fb_payments
        # FBE snapshots must not inherit hotel room tenders.
        if _hotel_invoice_source_value(payload.get("source")) == HOTEL_INVOICE_SOURCE_FB_COMBINED:
            payload_stay.pop("payments", None)
    payload["stay"] = payload_stay
    return payload


def _settle_fb_transfer_folio(stay, amount):
    """Mark unsettled F&B folio lines settled FIFO up to amount. Returns applied."""
    if not isinstance(stay, dict):
        return 0.0
    remaining = round(float(amount or 0), 2)
    if remaining <= 0.009:
        return 0.0
    folio = stay.get("folioCharges") or []
    if not isinstance(folio, list):
        return 0.0
    applied = 0.0
    for line in folio:
        if not isinstance(line, dict) or not _hotel_folio_is_fb_transfer(line):
            continue
        if line.get("settled"):
            continue
        line_amt = round(float(line.get("amount") or 0), 2)
        if line_amt <= 0.009:
            line["settled"] = True
            continue
        if remaining + 0.009 < line_amt:
            break
        line["settled"] = True
        remaining = round(remaining - line_amt, 2)
        applied = round(applied + line_amt, 2)
    return applied


def _append_fb_transfer_payment_record(
    stay, amount, *, method="", note="", reference="", invoice_number=""
):
    """Append one F&B tender payment row (does not settle folio lines)."""
    if not isinstance(stay, dict):
        return None
    pay_amt = round(float(amount or 0), 2)
    if pay_amt <= 0.009:
        return None
    payments = stay.get("fbTransferPayments")
    if not isinstance(payments, list):
        payments = []
    method_key = _normalize_hotel_payment_method(method) or "cash"
    inv_no = _hotel_str(
        invoice_number
        or stay.get("fbTransferInvoiceNumber")
        or stay.get("fb_transfer_invoice_number"),
        60,
    )
    record = {
        "id": f"fbpay-{len(payments) + 1}",
        "amount": pay_amt,
        "method": method_key,
        "reference": _hotel_str(reference, 80),
        "note": _hotel_str(note, 200),
        "invoiceNumber": inv_no,
        "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    payments.append(record)
    stay["fbTransferPayments"] = payments
    return record


def _apply_fb_transfer_payment(
    stay, amount, note="", *, method="", reference="", invoice_number=""
):
    """Apply amount against unsettled F&B transfer folio lines (FIFO) and record tender."""
    applied = _settle_fb_transfer_folio(stay, amount)
    if applied > 0:
        _append_fb_transfer_payment_record(
            stay,
            applied,
            method=method,
            note=note,
            reference=reference,
            invoice_number=invoice_number,
        )
    return applied


def _apply_fb_transfer_payment_splits(
    stay, splits, *, note="", invoice_number=""
):
    """Settle F&B folio for the combined split total, then record each tender."""
    if not isinstance(stay, dict):
        return []
    parsed = []
    for split in splits or []:
        if not isinstance(split, dict):
            continue
        amt = round(float(split.get("amount") or 0), 2)
        if amt <= 0.009:
            continue
        parsed.append(split)
    pay_total = round(sum(float(s.get("amount") or 0) for s in parsed), 2)
    applied = _settle_fb_transfer_folio(stay, pay_total)
    if applied <= 0.009:
        return []
    records = []
    remaining = applied
    for split in parsed:
        if remaining <= 0.009:
            break
        split_amt = round(float(split.get("amount") or 0), 2)
        take = round(min(split_amt, remaining), 2)
        if take <= 0.009:
            continue
        rec = _append_fb_transfer_payment_record(
            stay,
            take,
            method=split.get("method") or "cash",
            note=note or split.get("note") or "",
            reference=split.get("reference") or "",
            invoice_number=invoice_number,
        )
        if rec:
            records.append(rec)
        remaining = round(remaining - take, 2)
    return records


def _apply_combined_stay_payment_splits(stay, splits, *, note="", allow_credit=False):
    """Apply payment splits across hotel balance first, then F&B transfer balance."""
    hotel_bal = round(float(stay.get("balanceAmount") or 0), 2)
    fb_bal = _hotel_fb_transfer_unsettled_total(stay)
    combined = round(hotel_bal + fb_bal, 2)
    parsed = _parse_hotel_room_payment_splits(
        splits,
        combined,
        require_positive=False,
        allow_credit=allow_credit,
    )
    hotel_records = []
    fb_splits = []
    for split in parsed:
        amount = round(float(split.get("amount") or 0), 2)
        if amount <= 0.009:
            continue
        to_hotel = round(min(amount, hotel_bal), 2)
        if to_hotel > 0.009:
            rec = _append_hotel_room_payment(
                stay,
                {
                    "method": split.get("method"),
                    "amount": to_hotel,
                    "reference": split.get("reference"),
                    "note": note or split.get("note"),
                },
                allow_credit=allow_credit,
            )
            if rec:
                hotel_records.append(rec)
            hotel_bal = round(hotel_bal - to_hotel, 2)
            amount = round(amount - to_hotel, 2)
        if amount > 0.009:
            fb_splits.append(
                {
                    "method": split.get("method") or "cash",
                    "amount": amount,
                    "reference": split.get("reference") or "",
                    "note": note or split.get("note") or "",
                }
            )
    if fb_splits:
        _apply_fb_transfer_payment_splits(
            stay,
            fb_splits,
            note=note,
            invoice_number=_hotel_str(
                stay.get("fbTransferInvoiceNumber")
                or stay.get("fb_transfer_invoice_number"),
                60,
            ),
        )
    return hotel_records


def _hotel_invoice_status(balance_amount):
    bal = round(float(balance_amount or 0), 2)
    return "settled" if bal <= 0.009 else "open"


def _hotel_normalize_invoice_row_status(value):
    key = str(value or "open").strip().lower()
    if key in ("settled", "cancelled"):
        return key
    return "open"


def _hotel_stay_invoice_locked(stay):
    if not isinstance(stay, dict):
        return False
    if stay.get("invoiceEditOpen") or stay.get("invoice_edit_open"):
        return False
    return bool(
        stay.get("invoiceGenerated")
        and _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    )


def _hotel_stay_edit_unlocked(stay):
    if not isinstance(stay, dict):
        return False
    return bool(stay.get("invoiceEditOpen") or stay.get("invoice_edit_open"))


def _hotel_room_stay_editable(room):
    """True when charge edits are allowed on this room (occupied stay or ledger reopen)."""
    if not isinstance(room, dict):
        return False
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return False
    if _hotel_stay_edit_unlocked(stay):
        return True
    return _normalize_hotel_room_status(room.get("status")) == "occupied"


def _hotel_clear_detached_invoice_edit_stay(room):
    """Remove stay reattached for ledger edit when the room is no longer occupied."""
    if not isinstance(room, dict):
        return False
    if _normalize_hotel_room_status(room.get("status")) == "occupied":
        return False
    if not isinstance(room.get("stay"), dict):
        return False
    room.pop("stay", None)
    return True


def _hotel_restore_archived_invoice_stay_for_edit(conn, item, inv_no):
    """Reattach archived stay charges onto the room so Create Invoice can edit them."""
    archived_room = item.get("room") if isinstance(item.get("room"), dict) else {}
    room_id = _hotel_str(item.get("room_id") or archived_room.get("id"), 40)
    if not room_id:
        raise ValueError("Guest has checked out. Cancel this invoice to void it.")
    layout = get_hotel_rooms_layout(conn)
    rooms = list(layout.get("rooms") or [])
    target = _hotel_find_room(rooms, room_id)
    if not target:
        raise ValueError("Guest has checked out. Cancel this invoice to void it.")
    current_stay = target.get("stay") if isinstance(target.get("stay"), dict) else None
    if _normalize_hotel_room_status(target.get("status")) == "occupied" and current_stay:
        current_inv = _hotel_str(
            current_stay.get("invoiceNumber") or current_stay.get("invoice_number"),
            60,
        )
        if current_inv != inv_no:
            raise ValueError(
                "Room is occupied by another guest. Cancel this invoice to void it."
            )
    archived_stay = (
        archived_room.get("stay") if isinstance(archived_room.get("stay"), dict) else {}
    )
    stay = dict(archived_stay)
    stay["invoiceNumber"] = inv_no
    stay["invoiceGenerated"] = True
    stay["invoiceEditOpen"] = True
    target["stay"] = _normalize_hotel_room_stay(stay)
    for key in ("mergeRoomNumbers", "mergeRoomLabel", "mergeLabel", "numberDisplay"):
        if archived_room.get(key) is not None:
            target[key] = archived_room.get(key)
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    return get_hotel_room(conn, room_id) or target


def _hotel_find_live_room_for_invoice(conn, invoice_number):
    number = _hotel_str(invoice_number, 60)
    layout = get_hotel_rooms_layout(conn)
    if not number:
        return None, layout
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if not stay:
            continue
        if _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60) == number:
            return room, layout
    return None, layout


def _hotel_ensure_folio_charge_ids(stay):
    """Assign stable ids to folio lines missing them (ledger edit / legacy payloads)."""
    if not isinstance(stay, dict):
        return stay
    stay = dict(stay)
    folio = []
    changed = False
    for idx, item in enumerate(stay.get("folioCharges") or []):
        if not isinstance(item, dict):
            continue
        row = dict(item)
        if not _hotel_str(row.get("id"), 40):
            stamp = _hotel_str(row.get("at"), 40) or str(idx)
            amount = row.get("amount")
            label = _hotel_str(row.get("label"), 80)
            row["id"] = "fc" + str(abs(hash(f"folio:{idx}:{amount}:{label}:{stamp}")))[:8]
            changed = True
        folio.append(row)
    if changed:
        stay["folioCharges"] = folio
    return stay


def _hotel_sync_live_invoice_row(conn, room):
    """Refresh ledger payment balances when a numbered stay still exists."""
    if not isinstance(room, dict):
        return None
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return None
    if not _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60):
        return None
    _hotel_sync_all_invoice_rows(conn, room)
    return _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)


def _hotel_invoice_has_live_stay(conn, item, inv_no=None):
    """True when the invoice's room is occupied by the same invoice stay."""
    if not isinstance(item, dict):
        return False
    inv_no = _hotel_str(inv_no or item.get("invoice_number"), 60)
    room_id = _hotel_str(item.get("room_id") or (item.get("room") or {}).get("id"), 40)
    if not inv_no or not room_id:
        return False
    live = get_hotel_room(conn, room_id)
    if not live or _normalize_hotel_room_status(live.get("status")) != "occupied":
        return False
    stay = live.get("stay") if isinstance(live.get("stay"), dict) else None
    if not stay:
        return False
    live_inv = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    return live_inv == inv_no


def _hotel_invoice_room_conflict_message(conn, item, inv_no):
    """Return an error message when another guest occupies the invoice room."""
    if not isinstance(item, dict):
        return None
    room_id = _hotel_str(item.get("room_id") or (item.get("room") or {}).get("id"), 40)
    if not room_id:
        return None
    live = get_hotel_room(conn, room_id)
    if not live or _normalize_hotel_room_status(live.get("status")) != "occupied":
        return None
    stay = live.get("stay") if isinstance(live.get("stay"), dict) else None
    if not stay:
        return None
    live_inv = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    if live_inv != inv_no:
        return "Room is occupied by another guest. Cancel this invoice to void it."
    return None


def _hotel_sync_invoice_edit_to_live_room(conn, item, archived_room):
    """Mirror ledger edit payload onto the live in-house stay when it matches."""
    inv_no = _hotel_str(item.get("invoice_number"), 60)
    if not _hotel_invoice_has_live_stay(conn, item, inv_no):
        return None
    room_id = _hotel_str(item.get("room_id") or (archived_room or {}).get("id"), 40)
    if not room_id:
        return None
    layout = get_hotel_rooms_layout(conn)
    rooms = list(layout.get("rooms") or [])
    target = _hotel_find_room(rooms, room_id)
    if not target:
        return None
    stay = (archived_room or {}).get("stay") if isinstance((archived_room or {}).get("stay"), dict) else None
    if not stay:
        return None
    target["stay"] = _normalize_hotel_room_stay(dict(stay))
    for key in ("mergeRoomNumbers", "mergeRoomLabel", "mergeLabel", "numberDisplay"):
        if archived_room.get(key) is not None:
            target[key] = archived_room.get(key)
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    refreshed = get_hotel_room(conn, room_id)
    _hotel_sync_live_invoice_row(conn, refreshed)
    return refreshed


def _hotel_require_invoice_edit_open(item):
    room = item.get("room") if isinstance(item.get("room"), dict) else {}
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    if not _hotel_stay_edit_unlocked(stay):
        raise ValueError("Invoice is not open for editing. Use Edit from Invoice Ledger first.")
    return room


_HOTEL_SYSTEM_CHARGE_LABEL_KEYS = frozenset(
    {"room", "overstay", "extra_bed", "early_checkin", "late_checkout"}
)


def _hotel_normalize_charge_labels(raw):
    """Keep invoice display overrides for built-in charge lines."""
    out = {}
    if not isinstance(raw, dict):
        return out
    for key, val in raw.items():
        k = str(key or "").strip()
        if k not in _HOTEL_SYSTEM_CHARGE_LABEL_KEYS:
            continue
        lab = _hotel_str(val, 120)
        if lab:
            out[k] = lab
    return out


def _hotel_apply_stay_charge_label(stay, charge_key, label):
    """Store a custom ITEM label for room / overstay / extras lines."""
    if not isinstance(stay, dict):
        return stay
    key = str(charge_key or "").strip()
    if key not in _HOTEL_SYSTEM_CHARGE_LABEL_KEYS:
        return stay
    new_label = _hotel_str(label, 120)
    if not new_label:
        return stay
    labels = _hotel_normalize_charge_labels(stay.get("chargeLabels") or {})
    labels[key] = new_label
    stay["chargeLabels"] = labels
    return stay


def _hotel_set_nightly_rate_at(stay, night_index, rate_val):
    """Set roomRate for a single billable night index (creates nightlyRates if needed)."""
    if not isinstance(stay, dict):
        return stay
    try:
        idx = int(night_index)
    except (TypeError, ValueError):
        raise ValueError("Invalid night charge.") from None
    if idx < 0:
        raise ValueError("Invalid night charge.")
    try:
        rate = round(float(rate_val), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a room rate greater than zero.") from exc
    if rate <= 0:
        raise ValueError("Enter a room rate greater than zero.")
    try:
        booked = max(1, int(stay.get("nights") or 1))
    except (TypeError, ValueError):
        booked = 1
    try:
        billable = max(booked, int(stay.get("billableNights") or booked))
    except (TypeError, ValueError):
        billable = booked
    if idx >= billable:
        raise ValueError("Night is outside this stay.")
    default_rate = round(float(stay.get("roomRate") or 0), 2) or rate
    nightly = [
        dict(item) if isinstance(item, dict) else {}
        for item in (stay.get("nightlyRates") or [])
    ]
    while len(nightly) < billable:
        prev = nightly[-1].get("roomRate") if nightly else default_rate
        nightly.append(
            {
                "roomRate": prev,
                "date": "",
                "ratePlan": stay.get("ratePlan") or "",
            }
        )
    row = dict(nightly[idx])
    row["roomRate"] = rate
    nightly[idx] = row
    stay["nightlyRates"] = nightly
    if idx == 0:
        stay["roomRate"] = rate
    return stay


def _hotel_apply_booked_nightly_rate(stay, rate_val):
    """Set roomRate on booked nights (not overstay) across stay + merge rows."""
    if not isinstance(stay, dict):
        return stay
    try:
        rate = round(float(rate_val), 2)
    except (TypeError, ValueError):
        return stay
    if rate <= 0:
        return stay
    try:
        nights = max(1, int(stay.get("nights") or 1))
    except (TypeError, ValueError):
        nights = 1

    def _patch_nightly(raw):
        if not isinstance(raw, list) or not raw:
            return raw
        out = []
        for idx, item in enumerate(raw):
            row = dict(item) if isinstance(item, dict) else {}
            if idx < nights:
                row["roomRate"] = rate
            out.append(row)
        return out

    nightly = stay.get("nightlyRates")
    if isinstance(nightly, list) and nightly:
        stay["nightlyRates"] = _patch_nightly(nightly)

    merge_rates = stay.get("mergeRoomRates")
    if isinstance(merge_rates, list) and merge_rates:
        patched_merge = []
        for item in merge_rates:
            if not isinstance(item, dict):
                continue
            row = dict(item)
            if row.get("isPrimary") or row.get("is_primary"):
                row["roomRate"] = rate
                nested = row.get("nightlyRates")
                if isinstance(nested, list) and nested:
                    row["nightlyRates"] = _patch_nightly(nested)
            patched_merge.append(row)
        stay["mergeRoomRates"] = patched_merge
    return stay


def _hotel_apply_overstay_charge(stay, amount):
    """Spread an overstay total across the extra billable nights."""
    if amount is None:
        raise ValueError("Enter an amount.")
    amt = round(float(amount), 2)
    booked = max(1, int(stay.get("nights") or 1))
    billable = max(booked, int(stay.get("billableNights") or booked))
    extra = billable - booked
    if extra <= 0:
        raise ValueError("No overstay nights to edit.")
    rate_val = round(amt / extra, 2) if extra else amt
    nightly = [
        dict(item) if isinstance(item, dict) else {}
        for item in (stay.get("nightlyRates") or [])
    ]
    default_rate = round(float(stay.get("roomRate") or 0), 2)
    while len(nightly) < billable:
        prev = nightly[-1].get("roomRate") if nightly else default_rate
        nightly.append({"roomRate": prev, "date": "", "plan": stay.get("ratePlan") or ""})
    for idx in range(booked, billable):
        row = dict(nightly[idx])
        row["roomRate"] = rate_val
        nightly[idx] = row
    stay["nightlyRates"] = nightly
    return stay


def _hotel_mutate_stay_charge(stay, room_id, charge_key, label="", amount=None, rate=None):
    """Apply a charge-line edit to a stay dict (shared by room + ledger edit)."""
    key = str(charge_key or "").strip()
    if not key:
        raise ValueError("Charge key is required.")
    stay = _normalize_hotel_room_stay(dict(stay))
    if _hotel_stay_invoice_locked(stay):
        raise ValueError("Charges cannot be edited after the invoice is generated.")
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to edit charges."
        )
    try:
        amt = None if amount is None else round(float(amount), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid amount.") from exc
    try:
        rate_val = None if rate is None else round(float(rate), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid rate.") from exc
    if amt is not None and amt < 0:
        raise ValueError("Amount cannot be negative.")
    if rate_val is not None and rate_val < 0:
        raise ValueError("Rate cannot be negative.")
    new_label = _hotel_str(label, 120)
    room_id = str(room_id or "").strip()

    if key == "room":
        nights = max(1, int(stay.get("nights") or 1))
        if rate_val is None and amt is not None:
            rate_val = round(amt / nights, 2) if nights else amt
        if rate_val is None or rate_val <= 0:
            raise ValueError("Enter a room rate greater than zero.")
        stay["roomRate"] = rate_val
        stay["totalRate"] = round(rate_val * nights, 2)
        # Folio totals prefer nightlyRates; keep booked nights in sync so the
        # rate edit is not discarded on normalize.
        stay = _hotel_apply_booked_nightly_rate(stay, rate_val)
    elif key.startswith("night:"):
        try:
            night_idx = int(key.split(":", 1)[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid night charge.") from exc
        if rate_val is None and amt is not None:
            rate_val = amt
        if rate_val is None or rate_val <= 0:
            raise ValueError("Enter a room rate greater than zero.")
        stay = _hotel_set_nightly_rate_at(stay, night_idx, rate_val)
    elif key == "extra_bed":
        if amt is None:
            raise ValueError("Enter an amount.")
        stay["extraBedAmount"] = amt
        if amt <= 0:
            stay["extraBedQty"] = 0
            stay["extraBedRate"] = 0.0
            stay["extraBedNights"] = 0
        elif not stay.get("extraBedQty"):
            stay["extraBedQty"] = 1
            stay["extraBedRate"] = amt
            stay["extraBedNights"] = 1
    elif key == "early_checkin":
        if amt is None:
            raise ValueError("Enter an amount.")
        stay["earlyCheckinAmount"] = amt
        if amt <= 0:
            stay["earlyCheckinQty"] = 0
            stay["earlyCheckinRate"] = 0.0
            stay["earlyCheckinNights"] = 0
        elif not stay.get("earlyCheckinQty"):
            stay["earlyCheckinQty"] = 1
            stay["earlyCheckinRate"] = amt
            stay["earlyCheckinNights"] = 1
    elif key == "late_checkout":
        if amt is None:
            raise ValueError("Enter an amount.")
        stay["lateCheckoutAmount"] = amt
        if amt <= 0:
            stay["lateCheckoutQty"] = 0
            stay["lateCheckoutRate"] = 0.0
            stay["lateCheckoutNights"] = 0
        elif not stay.get("lateCheckoutQty"):
            stay["lateCheckoutQty"] = 1
            stay["lateCheckoutRate"] = amt
            stay["lateCheckoutNights"] = 1
    elif key == "overstay":
        stay = _hotel_apply_overstay_charge(stay, amt)
    elif key in ("restaurant_room_transfer", "bar_room_transfer"):
        if amt is None or amt <= 0:
            raise ValueError("Enter an amount greater than zero.")
        folio = [
            item
            for item in (stay.get("folioCharges") or [])
            if str(item.get("kind") or "").lower() != key
        ]
        folio.append(
            {
                "id": "fc" + str(abs(hash(f"{room_id}:{key}:{amt}")))[:8],
                "kind": key,
                "label": new_label
                or (
                    "Restaurant Room Transfer"
                    if key.startswith("restaurant")
                    else "Bar Room Transfer"
                ),
                "amount": amt,
                "source": "hotel_invoice",
                "invoiceId": "",
                "outlet": "",
                "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "note": "",
            }
        )
        stay["folioCharges"] = folio
    elif key.startswith("folio:"):
        folio_id = key.split(":", 1)[1].strip()
        if not folio_id:
            raise ValueError("Folio charge not found.")
        if amt is None or amt <= 0:
            raise ValueError("Enter an amount greater than zero.")
        found = False
        folio = []
        legacy_idx = None
        if folio_id.startswith("legacy-"):
            try:
                legacy_idx = int(folio_id.split("-", 1)[1]) - 1
            except (TypeError, ValueError):
                legacy_idx = -1
        for idx, item in enumerate(stay.get("folioCharges") or []):
            match = legacy_idx is not None and idx == legacy_idx
            if not match:
                match = str(item.get("id") or "") == folio_id
            if not match:
                folio.append(item)
                continue
            found = True
            updated = dict(item)
            updated["amount"] = amt
            if new_label:
                updated["label"] = new_label
            if not _hotel_str(updated.get("id"), 40):
                updated["id"] = folio_id if not folio_id.startswith("legacy-") else (
                    "fc" + str(abs(hash(f"folio:{idx}:{amt}:{updated.get('label')}")))[:8]
                )
            folio.append(updated)
        if not found:
            raise ValueError("Folio charge not found.")
        stay["folioCharges"] = folio
    else:
        raise ValueError("Unsupported charge line.")
    if key in _HOTEL_SYSTEM_CHARGE_LABEL_KEYS:
        stay = _hotel_apply_stay_charge_label(stay, key, new_label)
    elif key.startswith("night:") and new_label:
        stay = _hotel_apply_stay_charge_label(stay, "room", new_label)
    return _normalize_hotel_room_stay(stay)


def _hotel_delete_stay_charge(stay, charge_key):
    key = str(charge_key or "").strip()
    if not key:
        raise ValueError("Charge key is required.")
    if key == "room" or key.startswith("night:"):
        raise ValueError("Room tariff cannot be deleted.")
    stay = _normalize_hotel_room_stay(dict(stay))
    if _hotel_stay_invoice_locked(stay):
        raise ValueError("Charges cannot be deleted after the invoice is generated.")
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to delete charges."
        )
    if key == "extra_bed":
        stay["extraBedAmount"] = 0.0
        stay["extraBedQty"] = 0
        stay["extraBedRate"] = 0.0
        stay["extraBedNights"] = 0
    elif key == "early_checkin":
        stay["earlyCheckinAmount"] = 0.0
        stay["earlyCheckinQty"] = 0
        stay["earlyCheckinRate"] = 0.0
        stay["earlyCheckinNights"] = 0
    elif key == "late_checkout":
        stay["lateCheckoutAmount"] = 0.0
        stay["lateCheckoutQty"] = 0
        stay["lateCheckoutRate"] = 0.0
        stay["lateCheckoutNights"] = 0
    elif key in ("restaurant_room_transfer", "bar_room_transfer"):
        stay["folioCharges"] = [
            item
            for item in (stay.get("folioCharges") or [])
            if str(item.get("kind") or "").lower() != key
        ]
    elif key.startswith("folio:"):
        folio_id = key.split(":", 1)[1].strip()
        before = len(stay.get("folioCharges") or [])
        stay["folioCharges"] = [
            item
            for item in (stay.get("folioCharges") or [])
            if str(item.get("id") or "") != folio_id
        ]
        if len(stay.get("folioCharges") or []) == before:
            raise ValueError("Folio charge not found.")
    else:
        raise ValueError("Unsupported charge line.")
    return _normalize_hotel_room_stay(stay)


def _hotel_apply_stay_discount(stay, discount_type="pct", discount_value=0, discount_reason=""):
    stay = _normalize_hotel_room_stay(dict(stay))
    if _hotel_stay_invoice_locked(stay):
        raise ValueError("Discount cannot be changed after the invoice is generated.")
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to set the discount."
        )
    dtype = str(discount_type or "pct").strip().lower()
    if dtype not in ("pct", "inr"):
        dtype = "pct"
    try:
        dvalue = round(float(discount_value or 0), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid discount amount.") from exc
    if dvalue < 0:
        raise ValueError("Discount cannot be negative.")
    reason = _hotel_str(discount_reason, 200)
    room_charges = _hotel_stay_room_charges_amount(stay)
    extras = round(
        float(stay.get("extraBedAmount") or 0)
        + float(stay.get("earlyCheckinAmount") or 0)
        + float(stay.get("lateCheckoutAmount") or 0),
        2,
    )
    folio_total = round(
        sum(
            float(item.get("amount") or 0)
            for item in (stay.get("folioCharges") or [])
            if not _hotel_folio_is_fb_transfer(item)
        ),
        2,
    )
    gross = round(room_charges + extras + folio_total, 2)
    if dtype == "inr":
        amount = round(min(gross, dvalue), 2)
        effective_pct = (amount / gross * 100.0) if gross > 0 else 0.0
    else:
        dvalue = min(100.0, dvalue)
        amount = round(gross * (dvalue / 100.0), 2)
        effective_pct = dvalue
    if amount <= 0 or dvalue <= 0:
        dtype = "pct"
        dvalue = 0.0
        amount = 0.0
        reason = ""
    elif effective_pct > 15 and not reason:
        raise ValueError("Enter a reason for discounts over 15%.")
    elif effective_pct <= 15:
        reason = ""
    stay["discountType"] = dtype
    stay["discountValue"] = dvalue
    stay["discountAmount"] = amount
    stay["discountReason"] = reason
    return _normalize_hotel_room_stay(stay)


def _hotel_append_stay_folio_charge(
    stay,
    room_id,
    *,
    amount,
    kind=None,
    label="",
    source="hotel_invoice",
    note="",
):
    amount = round(float(amount or 0), 2)
    if amount <= 0:
        raise ValueError("Folio charge amount must be greater than zero.")
    stay = _normalize_hotel_room_stay(dict(stay))
    if _hotel_stay_invoice_locked(stay):
        raise ValueError("Custom charges cannot be added after the invoice is generated.")
    folio_kind = kind or "other"
    if folio_kind not in ("restaurant_room_transfer", "bar_room_transfer", "other"):
        folio_kind = "other"
    default_label = {
        "restaurant_room_transfer": "Restaurant Room Transfer",
        "bar_room_transfer": "Bar Room Transfer",
        "other": "Other Charge",
    }.get(folio_kind, "Other Charge")
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line_id = "fc" + str(abs(hash(f"{room_id}:{amount}:{stamp}")))[:8]
    stored_label = str(label or default_label).strip()[:120] or default_label
    line = {
        "id": line_id,
        "kind": folio_kind,
        "label": stored_label,
        "amount": amount,
        "source": str(source or "hotel_invoice").strip()[:40],
        "invoiceId": "",
        "orderNo": "",
        "outlet": "",
        "at": stamp,
        "note": str(note or "").strip()[:200],
        "settled": False,
    }
    folio = list(stay.get("folioCharges") or [])
    folio.append(line)
    stay["folioCharges"] = folio
    return _normalize_hotel_room_stay(stay), line


def _hotel_persist_archived_invoice_edit(conn, item, archived_room):
    upsert_hotel_room_invoice_from_room(conn, archived_room)
    _hotel_sync_invoice_edit_to_live_room(conn, item, archived_room)
    inv_no = _hotel_str(item.get("invoice_number"), 60)
    refreshed = get_hotel_room_invoice(conn, inv_no)
    return refreshed.get("room") if refreshed else archived_room


def _hotel_invoice_guest_name(stay):
    if not isinstance(stay, dict):
        return ""
    name = _hotel_str(stay.get("guestName") or stay.get("guest_name"), 160)
    if name:
        return name
    first = _hotel_str(stay.get("firstName") or stay.get("first_name"), 80)
    last = _hotel_str(stay.get("lastName") or stay.get("last_name"), 80)
    return f"{first} {last}".strip()


def _hotel_invoice_frozen_room_display(existing_row, stay, room):
    """Ledger ROOM column is fixed at mint — never shrink when peers check out."""
    column_label = ""
    payload_label = ""
    if existing_row is not None:
        try:
            column_label = _hotel_str(existing_row["room_number"], 80)
        except (KeyError, IndexError, TypeError):
            column_label = ""
        try:
            payload = json.loads(existing_row["payload_json"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError, KeyError, IndexError):
            payload = {}
        if isinstance(payload, dict):
            payload_label = _hotel_str(
                payload.get("mergeRoomLabel")
                or (payload.get("stay") or {}).get("mergeRoomLabel"),
                80,
            )
    # Prefer the broader invoice-time roster (heals rows already shrunk by checkout).
    if payload_label and column_label:
        if payload_label.count("+") > column_label.count("+") or (
            len(payload_label) > len(column_label)
            and "+" in payload_label
        ):
            return payload_label
        return column_label
    if column_label:
        return column_label
    if payload_label:
        return payload_label
    return _hotel_str(
        (stay or {}).get("mergeRoomLabel") or (room or {}).get("number"), 80
    ) or _hotel_str((room or {}).get("number"), 20)


def _hotel_preserve_invoice_merge_roster(payload, stay):
    """Keep invoice-time merge rooms on the payload when live peers shrink."""
    if not isinstance(payload, dict):
        payload = {}
    prev_nums = payload.get("mergeRoomNumbers") or []
    if not isinstance(prev_nums, list):
        prev_nums = []
    prev_label = _hotel_str(payload.get("mergeRoomLabel"), 120)
    live_nums = []
    if isinstance(stay, dict):
        raw = stay.get("mergeRoomNumbers") or []
        if isinstance(raw, list):
            for item in raw[:20]:
                num = _hotel_str(item, 20)
                if num and num not in live_nums:
                    live_nums.append(num)
        live_label = _hotel_str(stay.get("mergeRoomLabel"), 120)
    else:
        live_label = ""
    kept = []
    for item in prev_nums[:20]:
        num = _hotel_str(item, 20)
        if num and num not in kept:
            kept.append(num)
    # Prefer the broader invoice-time roster over a shrunken live merge.
    if len(kept) > 1 or (prev_label and "+" in prev_label):
        payload["mergeRoomNumbers"] = kept or live_nums
        payload["mergeRoomLabel"] = prev_label or (
            " + ".join(kept) if kept else live_label
        )
    elif live_nums or live_label:
        payload["mergeRoomNumbers"] = live_nums
        payload["mergeRoomLabel"] = live_label or " + ".join(live_nums)
    return payload


def upsert_hotel_room_invoice_from_room(
    conn, room, invoice_number=None, snapshot_stay=None, estimated_total=None, created_by=""
):
    """Persist / refresh a ledger row from an occupied (or snapshot) room dict."""
    if not isinstance(room, dict):
        return None
    room = dict(room)
    try:
        layout_rooms = get_hotel_rooms_layout(conn).get("rooms") or []
    except Exception:
        layout_rooms = None
    _hotel_snapshot_merge_rooms_on_stay(room, layout_rooms)
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return None
    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    invoice_number = _hotel_str(
        invoice_number or stay.get("invoiceNumber") or stay.get("invoice_number"), 60
    )
    if not invoice_number:
        return None
    ensure_hotel_room_invoices_schema(conn)

    existing = _hotel_get_invoice_ledger_row(conn, invoice_number)
    balances = _hotel_allocate_hotel_invoice_balances(stay)
    balance = round(float(balances.get(invoice_number, stay.get("balanceAmount") or 0)), 2)
    advance = round(float(stay.get("advancePaid") or 0), 2)
    status = _hotel_invoice_status(balance)
    generated_at = _hotel_str(
        stay.get("invoiceGeneratedAt") or stay.get("invoice_generated_at"), 40
    ) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if existing and str(existing["status"] or "").strip().lower() == "cancelled":
        return invoice_number

    if existing:
        try:
            payload = json.loads(existing["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload_stay = (
            payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
        )
        # While an invoice edit session is open (or being closed), replace the
        # snapshot stay so charge edits persist on the ledger row.
        editing = _hotel_stay_edit_unlocked(stay) or _hotel_stay_edit_unlocked(
            payload_stay
        )
        if editing:
            payload = dict(payload)
            for key in (
                "id",
                "number",
                "roomType",
                "roomTypeLabel",
                "floorId",
                "status",
            ):
                if room.get(key) is not None:
                    payload[key] = room.get(key)
            payload = _hotel_preserve_invoice_merge_roster(payload, stay)
            payload["stay"] = stay
            estimated = round(
                float(stay.get("estimatedTotal") or existing["estimated_total"] or 0),
                2,
            )
        else:
            payload = _hotel_merge_live_payments_into_payload(payload, stay)
            estimated = round(float(existing["estimated_total"] or 0), 2)
        generated_at = _hotel_str(existing["invoice_generated_at"], 40) or generated_at
        blob = json.dumps(payload, separators=(",", ":"))
    else:
        snap = snapshot_stay if isinstance(snapshot_stay, dict) else stay
        if estimated_total is not None:
            estimated = round(float(estimated_total), 2)
        else:
            for entry in _hotel_invoice_history_entries(stay, kind="hotel"):
                if entry["invoiceNumber"] == invoice_number:
                    estimated = round(float(entry.get("estimatedTotal") or 0), 2)
                    break
            else:
                estimated = round(float(snap.get("estimatedTotal") or stay.get("estimatedTotal") or 0), 2)
        snap = _hotel_build_hotel_invoice_snapshot_stay(snap, invoice_number, estimated)
        snap["balanceAmount"] = balance
        snap["advancePaid"] = advance
        # Snapshot may be captured before generate_invoice payment_splits; merge
        # live tenders so Sales Entry (Guest Credit / BOR) sees the settlement.
        snap = (
            _hotel_merge_live_payments_into_payload({"stay": snap}, stay).get("stay")
            or snap
        )
        payload = {
            "id": room.get("id") or "",
            "number": room.get("number") or "",
            "roomType": room.get("roomType") or room.get("room_type") or "",
            "roomTypeLabel": room.get("roomTypeLabel")
            or room.get("room_type_label")
            or "",
            "floorId": room.get("floorId") or room.get("floor_id") or "",
            "status": room.get("status") or "occupied",
            "mergeRoomNumbers": list(stay.get("mergeRoomNumbers") or []),
            "mergeRoomLabel": stay.get("mergeRoomLabel") or "",
            "stay": snap,
        }
        blob = json.dumps(payload, separators=(",", ":"))

    room_number_display = _hotel_invoice_frozen_room_display(existing, stay, room)
    creator = _hotel_str(created_by, 160)
    if not creator:
        creator = _hotel_str(
            stay.get("invoiceCreatedBy") or stay.get("invoice_created_by"), 160
        )
    if not creator and existing:
        try:
            creator = _hotel_str(existing["created_by"], 160)
        except (KeyError, IndexError, TypeError):
            creator = ""
    conn.execute(
        """
        INSERT INTO hotel_room_invoices (
            invoice_number, room_id, room_number, room_type_label,
            guest_name, booking_number, check_in_date, check_out_date,
            invoice_generated_at, estimated_total, advance_paid, balance_amount,
            status, payload_json, created_by, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(invoice_number) DO UPDATE SET
            room_id = excluded.room_id,
            room_number = excluded.room_number,
            room_type_label = excluded.room_type_label,
            guest_name = excluded.guest_name,
            booking_number = excluded.booking_number,
            check_in_date = excluded.check_in_date,
            check_out_date = excluded.check_out_date,
            invoice_generated_at = COALESCE(
                NULLIF(hotel_room_invoices.invoice_generated_at, ''),
                excluded.invoice_generated_at
            ),
            estimated_total = COALESCE(
                NULLIF(hotel_room_invoices.estimated_total, 0),
                excluded.estimated_total
            ),
            advance_paid = excluded.advance_paid,
            balance_amount = excluded.balance_amount,
            status = excluded.status,
            payload_json = excluded.payload_json,
            created_by = COALESCE(
                NULLIF(hotel_room_invoices.created_by, ''),
                excluded.created_by
            ),
            updated_at = datetime('now','localtime')
        WHERE hotel_room_invoices.status != 'cancelled'
        """,
        (
            invoice_number,
            _hotel_str(room.get("id"), 40),
            room_number_display,
            _hotel_str(
                room.get("roomTypeLabel") or room.get("room_type_label"), 80
            ),
            _hotel_invoice_guest_name(stay),
            _hotel_str(stay.get("bookingNumber") or stay.get("booking_number"), 40),
            _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 10),
            _hotel_str(stay.get("checkOutDate") or stay.get("check_out_date"), 10),
            generated_at,
            estimated,
            advance,
            balance,
            status,
            blob,
            creator,
        ),
    )
    return invoice_number


def _hotel_invoice_source_value(value):
    key = str(value or "").strip().lower()
    if key == HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        return HOTEL_INVOICE_SOURCE_POS_TRANSFER
    if key == HOTEL_INVOICE_SOURCE_FB_COMBINED:
        return HOTEL_INVOICE_SOURCE_FB_COMBINED
    return HOTEL_INVOICE_SOURCE_HOTEL


def _hotel_fb_transfer_linked_pos_orders(stay):
    linked = []
    for line in _hotel_fb_transfer_lines(stay):
        order_no = _hotel_str(line.get("orderNo") or line.get("order_no"), 60)
        if not order_no:
            continue
        linked.append(
            {
                "orderNo": order_no,
                "outlet": _hotel_str(line.get("outlet"), 40),
                "amount": round(float(line.get("amount") or 0), 2),
                "posInvoiceId": _hotel_str(
                    line.get("invoiceId") or line.get("invoice_id"), 40
                ),
            }
        )
    return linked


def _retire_pos_room_transfer_invoices_for_stay(conn, stay, fb_invoice_number=""):
    """Cancel open per-POS ledger rows superseded by a combined FBE invoice."""
    if not isinstance(stay, dict):
        return 0
    ensure_hotel_room_invoices_schema(conn)
    fb_no = _hotel_str(fb_invoice_number or stay.get("fbTransferInvoiceNumber"), 60)
    reason = f"Combined into {fb_no}" if fb_no else "Combined into F&B transfer invoice"
    count = 0
    for line in _hotel_fb_transfer_lines(stay):
        order_no = _hotel_str(line.get("orderNo") or line.get("order_no"), 60)
        line_fbe = _hotel_folio_line_invoiced_no(line) or fb_no
        if not order_no:
            continue
        count += _retire_pos_room_transfer_invoice(
            conn, order_no, line_fbe or fb_no, reason=reason
        )
    return count


def _retire_pos_room_transfer_invoice(conn, order_no, fb_invoice_number="", reason=""):
    """Mark one per-POS room-transfer ledger row as combined into an FBE."""
    ensure_hotel_room_invoices_schema(conn)
    order_no = _hotel_str(order_no, 60)
    if not order_no:
        return 0
    ledger_no = _pos_room_transfer_ledger_invoice_number(conn, order_no) or order_no
    fb_no = _hotel_str(fb_invoice_number, 60)
    reason_text = _hotel_str(reason, 500) or (
        f"Combined into {fb_no}" if fb_no else "Combined into F&B transfer invoice"
    )
    existing = conn.execute(
        """
        SELECT status, cancel_reason, payload_json
        FROM hotel_room_invoices
        WHERE invoice_number = ? AND source = ?
        """,
        (ledger_no, HOTEL_INVOICE_SOURCE_POS_TRANSFER),
    ).fetchone()
    if not existing:
        return 0
    status = str(existing["status"] or "").strip().lower()
    try:
        payload = json.loads(existing["payload_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["posOrderNo"] = order_no
    if fb_no:
        payload["fbCombinedInvoiceNumber"] = fb_no
        stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
        stay = dict(stay)
        stay["fbTransferInvoiceNumber"] = fb_no
        stay["fbTransferInvoiceGenerated"] = True
        payload["stay"] = stay
    blob = json.dumps(payload, separators=(",", ":"))
    if status == "cancelled":
        # Keep payload/FBE link fresh even when already cancelled.
        if fb_no and not _hotel_fb_invoice_from_cancel_reason(existing["cancel_reason"]):
            conn.execute(
                """
                UPDATE hotel_room_invoices
                SET cancel_reason = ?,
                    payload_json = ?,
                    updated_at = datetime('now','localtime')
                WHERE invoice_number = ?
                  AND source = ?
                """,
                (reason_text, blob, ledger_no, HOTEL_INVOICE_SOURCE_POS_TRANSFER),
            )
        elif fb_no:
            conn.execute(
                """
                UPDATE hotel_room_invoices
                SET payload_json = ?,
                    updated_at = datetime('now','localtime')
                WHERE invoice_number = ?
                  AND source = ?
                """,
                (blob, ledger_no, HOTEL_INVOICE_SOURCE_POS_TRANSFER),
            )
        return 0
    if status not in ("open", "settled"):
        return 0
    conn.execute(
        """
        UPDATE hotel_room_invoices
        SET status = 'cancelled',
            cancel_reason = ?,
            cancelled_at = datetime('now','localtime'),
            balance_amount = 0,
            payload_json = ?,
            updated_at = datetime('now','localtime')
        WHERE invoice_number = ?
          AND source = ?
          AND status IN ('open', 'settled')
        """,
        (reason_text, blob, ledger_no, HOTEL_INVOICE_SOURCE_POS_TRANSFER),
    )
    return 1


def upsert_fb_combined_transfer_invoice(
    conn, room, invoice_number=None, transfer_lines=None, created_by=""
):
    """Persist the combined restaurant+bar room-transfer invoice (FBE) ledger row."""
    if not isinstance(room, dict):
        return None
    room = dict(room)
    try:
        layout_rooms = get_hotel_rooms_layout(conn).get("rooms") or []
    except Exception:
        layout_rooms = None
    _hotel_snapshot_merge_rooms_on_stay(room, layout_rooms)
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return None
    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    invoice_number = _hotel_str(
        invoice_number or stay.get("fbTransferInvoiceNumber"), 60
    )
    if not invoice_number:
        return None
    if transfer_lines is None:
        transfer_lines = [
            dict(line)
            for line in _hotel_fb_transfer_lines(stay)
            if _hotel_folio_line_invoiced_no(line) == invoice_number
        ]
        if not transfer_lines:
            untagged = [
                line
                for line in _hotel_fb_transfer_lines(stay)
                if not _hotel_folio_line_invoiced_no(line)
            ]
            if (
                invoice_number
                == _hotel_str(stay.get("fbTransferInvoiceNumber"), 60)
                and untagged
                and not any(
                    _hotel_folio_line_invoiced_no(l) for l in _hotel_fb_transfer_lines(stay)
                )
            ):
                transfer_lines = [dict(line) for line in _hotel_fb_transfer_lines(stay)]
    if not transfer_lines:
        return None
    ensure_hotel_room_invoices_schema(conn)

    existing = _hotel_get_invoice_ledger_row(conn, invoice_number)
    fb_balances = _hotel_allocate_fb_invoice_balances(stay)
    fb_balance = round(float(fb_balances.get(invoice_number, 0)), 2)
    fb_total = round(sum(float(line.get("amount") or 0) for line in transfer_lines), 2)
    fb_advance = round(max(0.0, fb_total - fb_balance), 2)
    status = _hotel_invoice_status(fb_balance)
    generated_at = _hotel_str(stay.get("fbTransferInvoiceGeneratedAt"), 40) or datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    if existing and str(existing["status"] or "").strip().lower() == "cancelled":
        return invoice_number

    if existing:
        try:
            payload = json.loads(existing["payload_json"] or "{}")
        except (TypeError, ValueError):
            payload = {}
        payload = _hotel_merge_live_payments_into_payload(payload, stay)
        fb_total = round(float(existing["estimated_total"] or fb_total), 2)
        generated_at = _hotel_str(existing["invoice_generated_at"], 40) or generated_at
        blob = json.dumps(payload, separators=(",", ":"))
    else:
        for entry in _hotel_invoice_history_entries(stay, kind="fb"):
            if entry["invoiceNumber"] == invoice_number:
                generated_at = entry.get("generatedAt") or generated_at
                break
        slim_stay = _hotel_build_fb_invoice_snapshot_stay(
            stay, invoice_number, transfer_lines, generated_at
        )
        slim_stay["balanceAmount"] = fb_balance
        slim_stay["advancePaid"] = fb_advance
        linked = []
        for line in transfer_lines:
            order_no = _hotel_str(line.get("orderNo") or line.get("order_no"), 60)
            if not order_no:
                continue
            linked.append(
                {
                    "orderNo": order_no,
                    "outlet": _hotel_str(line.get("outlet"), 40),
                    "amount": round(float(line.get("amount") or 0), 2),
                    "posInvoiceId": _hotel_str(
                        line.get("invoiceId") or line.get("invoice_id"), 40
                    ),
                }
            )
        room_number_display = _hotel_str(
            stay.get("mergeRoomLabel") or room.get("number"), 80
        ) or _hotel_str(room.get("number"), 20)
        payload = {
            "id": room.get("id") or "",
            "number": room.get("number") or "",
            "roomType": room.get("roomType") or room.get("room_type") or "",
            "roomTypeLabel": "F&B Transfers",
            "floorId": room.get("floorId") or room.get("floor_id") or "",
            "status": room.get("status") or "occupied",
            "mergeRoomNumbers": list(stay.get("mergeRoomNumbers") or []),
            "mergeRoomLabel": stay.get("mergeRoomLabel") or "",
            "source": HOTEL_INVOICE_SOURCE_FB_COMBINED,
            "linkedPosOrders": linked,
            "stayInvoiceNumber": _hotel_str(stay.get("invoiceNumber"), 60),
            "stay": slim_stay,
        }
        blob = json.dumps(payload, separators=(",", ":"))

    guest_name = _hotel_invoice_guest_name(stay)
    room_number_display = _hotel_invoice_frozen_room_display(existing, stay, room)
    creator = _hotel_str(created_by, 160)
    if not creator:
        creator = _hotel_str(
            stay.get("invoiceCreatedBy") or stay.get("invoice_created_by"), 160
        )
    if not creator and existing:
        try:
            creator = _hotel_str(existing["created_by"], 160)
        except (KeyError, IndexError, TypeError):
            creator = ""
    conn.execute(
        """
        INSERT INTO hotel_room_invoices (
            invoice_number, room_id, room_number, room_type_label,
            guest_name, booking_number, check_in_date, check_out_date,
            invoice_generated_at, estimated_total, advance_paid, balance_amount,
            status, source, payload_json, created_by, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(invoice_number) DO UPDATE SET
            room_id = excluded.room_id,
            room_number = excluded.room_number,
            room_type_label = excluded.room_type_label,
            guest_name = excluded.guest_name,
            booking_number = excluded.booking_number,
            check_in_date = excluded.check_in_date,
            check_out_date = excluded.check_out_date,
            invoice_generated_at = COALESCE(
                NULLIF(hotel_room_invoices.invoice_generated_at, ''),
                excluded.invoice_generated_at
            ),
            estimated_total = COALESCE(
                NULLIF(hotel_room_invoices.estimated_total, 0),
                excluded.estimated_total
            ),
            advance_paid = excluded.advance_paid,
            balance_amount = excluded.balance_amount,
            status = excluded.status,
            source = excluded.source,
            payload_json = excluded.payload_json,
            created_by = COALESCE(
                NULLIF(hotel_room_invoices.created_by, ''),
                excluded.created_by
            ),
            updated_at = datetime('now','localtime')
        WHERE hotel_room_invoices.status != 'cancelled'
        """,
        (
            invoice_number,
            _hotel_str(room.get("id"), 40),
            room_number_display,
            "F&B Transfers",
            guest_name,
            _hotel_str(stay.get("bookingNumber") or stay.get("booking_number"), 40),
            _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 10),
            _hotel_str(stay.get("checkOutDate") or stay.get("check_out_date"), 10),
            generated_at,
            fb_total,
            fb_advance,
            fb_balance,
            status,
            HOTEL_INVOICE_SOURCE_FB_COMBINED,
            blob,
            creator,
        ),
    )
    return invoice_number


def _hotel_sync_all_invoice_rows(conn, room):
    """Refresh payment balances on every minted HBE/FBE row without mutating charges."""
    if not isinstance(room, dict):
        return
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return
    stay = _normalize_hotel_room_stay(stay)
    room = dict(room)
    room["stay"] = stay
    for entry in _hotel_invoice_history_entries(stay, kind="hotel"):
        inv = entry.get("invoiceNumber")
        snap = entry.get("snapshotStay")
        upsert_hotel_room_invoice_from_room(
            conn,
            room,
            invoice_number=inv,
            snapshot_stay=snap,
            estimated_total=entry.get("estimatedTotal"),
        )
    for entry in _hotel_invoice_history_entries(stay, kind="fb"):
        inv = entry.get("invoiceNumber")
        lines = [
            dict(line)
            for line in _hotel_fb_transfer_lines(stay)
            if _hotel_folio_line_invoiced_no(line) == inv
        ]
        upsert_fb_combined_transfer_invoice(conn, room, invoice_number=inv, transfer_lines=lines)


def generate_fb_transfer_invoice(conn, room_id):
    """Mint FBE once when unsettled restaurant/bar transfers exist on the stay."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    room = None
    for item in rooms:
        if item.get("id") == target or item.get("number") == target:
            room = item
            break
    if not room:
        raise ValueError("Room not found.")
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("No guest stay on this room.")
    stay = _normalize_hotel_room_stay(stay)
    pending_lines = _hotel_pending_fb_transfer_lines(stay)
    if not pending_lines:
        if _hotel_fb_transfer_total(stay) <= 0.009:
            return None
        pending_lines = _hotel_fb_transfer_lines(stay)
    minted = False
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    minted_fb_no = allocate_fb_transfer_invoice_number(conn)
    if not stay.get("fbTransferInvoiceNumber"):
        stay["fbTransferInvoiceNumber"] = minted_fb_no
        stay["fbTransferInvoiceGeneratedAt"] = now
    minted = True
    folio_ids = [
        _hotel_str(line.get("id"), 40)
        for line in pending_lines
        if _hotel_str(line.get("id"), 40)
    ]
    id_set = set(folio_ids)
    _hotel_tag_folio_lines(
        stay,
        minted_fb_no,
        lambda line: _hotel_str(line.get("id"), 40) in id_set,
    )
    fb_amount = round(sum(float(l.get("amount") or 0) for l in pending_lines), 2)
    snap_fb = _hotel_build_fb_invoice_snapshot_stay(stay, minted_fb_no, pending_lines, now)
    _hotel_append_invoice_history(
        stay,
        {
            "kind": "fb",
            "invoiceNumber": minted_fb_no,
            "generatedAt": now,
            "estimatedTotal": fb_amount,
            "balanceAmount": fb_amount,
            "billableNights": 0,
            "folioLineIds": folio_ids,
            "snapshotStay": snap_fb,
        },
    )
    stay["fbTransferInvoiceGenerated"] = True
    if not stay.get("fbTransferInvoiceGeneratedAt"):
        stay["fbTransferInvoiceGeneratedAt"] = now
    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    refreshed = get_hotel_room(conn, room.get("id") or target)
    if refreshed:
        room = refreshed
    _hotel_sync_all_invoice_rows(conn, room)
    _retire_pos_room_transfer_invoices_for_stay(
        conn, stay, minted_fb_no
    )
    return {
        "room": room,
        "minted": minted,
        "invoiceNumber": minted_fb_no,
        "linkedPosOrders": _hotel_fb_transfer_linked_pos_orders(
            {"folioCharges": pending_lines}
        ),
    }


def _pos_room_transfer_outlet_label(folio_line):
    kind = str((folio_line or {}).get("kind") or "").strip().lower()
    outlet = str((folio_line or {}).get("outlet") or "").strip().lower()
    if kind == "bar_room_transfer" or "bar" in outlet:
        return "Bar"
    return "Restaurant"


def upsert_pos_room_transfer_invoice(conn, room, folio_line):
    """List a POS room-transfer bill on the hotel invoice ledger as Un Settled."""
    if not isinstance(room, dict) or not isinstance(folio_line, dict):
        return None
    stay_in = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    stay = _normalize_hotel_room_stay(dict(stay_in)) if stay_in else {}
    order_no = _hotel_str(
        folio_line.get("orderNo") or folio_line.get("order_no"), 60
    )
    if not order_no:
        return None
    amount = round(float(folio_line.get("amount") or 0), 2)
    if amount <= 0:
        return None
    ensure_hotel_room_invoices_schema(conn)
    # Already rolled into an FBE — never recreate as "Invoice yet to generate".
    fbe_no = _hotel_folio_line_invoiced_no(folio_line)
    if fbe_no:
        _retire_pos_room_transfer_invoice(conn, order_no, fbe_no)
        return order_no
    ledger_no = _pos_room_transfer_ledger_invoice_number(conn, order_no)
    existing = None
    if ledger_no:
        existing = conn.execute(
            """
            SELECT invoice_number, status, advance_paid, balance_amount,
                   estimated_total, payload_json, cancel_reason
            FROM hotel_room_invoices
            WHERE invoice_number = ?
            """,
            (ledger_no,),
        ).fetchone()
    if existing and str(existing["status"] or "").strip().lower() == "cancelled":
        # Keep cancelled combined rows stable; do not reopen.
        return order_no
    if not ledger_no:
        ledger_no = allocate_room_transfer_invoice_number(conn)
    folio_settled = bool(folio_line.get("settled"))
    already_settled = bool(
        existing
        and (
            str(existing["status"] or "") == "settled"
            or float(existing["balance_amount"] or 0) <= 0.009
        )
    )
    mark_settled = already_settled or folio_settled
    advance = amount if mark_settled else 0.0
    balance = 0.0 if mark_settled else amount
    status = "settled" if mark_settled else "open"
    generated_at = _hotel_str(folio_line.get("at"), 40) or datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    outlet_label = _pos_room_transfer_outlet_label(folio_line)
    guest_name = _hotel_invoice_guest_name(stay)
    agency_name = _hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160)
    slim_stay = {
        "title": stay.get("title") or "",
        "firstName": stay.get("firstName") or "",
        "lastName": stay.get("lastName") or "",
        "guestName": guest_name,
        "mobile": stay.get("mobile") or "",
        "checkInDate": stay.get("checkInDate") or "",
        "checkOutDate": stay.get("checkOutDate") or "",
        "nights": 1,
        "roomRate": 0,
        "bookingNumber": stay.get("bookingNumber") or "",
        "agencyName": agency_name,
        "agency_name": agency_name,
        "invoiceNumber": ledger_no,
        "invoiceGenerated": True,
        "invoiceGeneratedAt": generated_at,
        "folioCharges": [dict(folio_line)],
        "payments": [],
        "advancePaid": advance,
        "checkInAdvancePaid": 0,
    }
    if mark_settled and amount > 0:
        slim_stay["payments"] = [
            {
                "id": "pay-pos-transfer",
                "amount": amount,
                "method": "cash",
                "note": "Room transfer collected with stay",
                "at": generated_at,
            }
        ]
    slim_stay = _normalize_hotel_room_stay(slim_stay)
    slim_stay["invoiceNumber"] = ledger_no
    slim_stay["invoiceGenerated"] = True
    payload = {
        "id": room.get("id") or "",
        "number": room.get("number") or "",
        "roomType": room.get("roomType") or room.get("room_type") or "",
        "roomTypeLabel": outlet_label,
        "floorId": room.get("floorId") or room.get("floor_id") or "",
        "status": room.get("status") or "occupied",
        "source": HOTEL_INVOICE_SOURCE_POS_TRANSFER,
        "posOrderNo": order_no,
        "posInvoiceId": _hotel_str(
            folio_line.get("invoiceId") or folio_line.get("invoice_id"), 40
        ),
        "folioId": _hotel_str(folio_line.get("id"), 40),
        "outlet": _hotel_str(folio_line.get("outlet"), 40),
        "stayInvoiceNumber": _hotel_str(
            stay.get("invoiceNumber") or stay.get("invoice_number"), 60
        ),
        "stay": slim_stay,
    }
    if existing and already_settled:
        return order_no
    blob = json.dumps(payload, separators=(",", ":"))
    creator = ""
    pos_invoice_id = _hotel_str(
        folio_line.get("invoiceId") or folio_line.get("invoice_id"), 40
    )
    if pos_invoice_id:
        try:
            pos_row = conn.execute(
                "SELECT created_by FROM pos_invoices WHERE id = ?",
                (int(pos_invoice_id),),
            ).fetchone()
            if pos_row:
                creator = _hotel_str(pos_row["created_by"], 160)
        except (TypeError, ValueError):
            creator = ""
    if not creator:
        creator = _hotel_str(
            stay.get("invoiceCreatedBy") or stay.get("invoice_created_by"), 160
        )
    if not creator and existing:
        try:
            creator = _hotel_str(existing["created_by"], 160)
        except (KeyError, IndexError, TypeError):
            creator = ""
    conn.execute(
        """
        INSERT INTO hotel_room_invoices (
            invoice_number, room_id, room_number, room_type_label,
            guest_name, booking_number, check_in_date, check_out_date,
            invoice_generated_at, estimated_total, advance_paid, balance_amount,
            status, source, payload_json, created_by, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(invoice_number) DO UPDATE SET
            room_id = excluded.room_id,
            room_number = excluded.room_number,
            room_type_label = excluded.room_type_label,
            guest_name = excluded.guest_name,
            booking_number = excluded.booking_number,
            check_in_date = excluded.check_in_date,
            check_out_date = excluded.check_out_date,
            estimated_total = excluded.estimated_total,
            advance_paid = excluded.advance_paid,
            balance_amount = excluded.balance_amount,
            status = excluded.status,
            source = excluded.source,
            payload_json = excluded.payload_json,
            created_by = COALESCE(
                NULLIF(hotel_room_invoices.created_by, ''),
                excluded.created_by
            ),
            updated_at = datetime('now','localtime')
        WHERE hotel_room_invoices.status != 'cancelled'
        """,
        (
            ledger_no,
            _hotel_str(room.get("id"), 40),
            _hotel_str(stay.get("mergeRoomLabel") or room.get("number"), 80)
            or _hotel_str(room.get("number"), 20),
            outlet_label,
            guest_name,
            _hotel_str(stay.get("bookingNumber") or stay.get("booking_number"), 40),
            _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 10),
            _hotel_str(stay.get("checkOutDate") or stay.get("check_out_date"), 10),
            generated_at,
            amount,
            advance,
            balance,
            status,
            HOTEL_INVOICE_SOURCE_POS_TRANSFER,
            blob,
            creator,
        ),
    )
    return order_no


def backfill_pos_room_transfer_invoices_from_layout(conn):
    """Create ledger rows for in-house POS folio transfers that are missing.

    Also heals open rows whose folio lines were already rolled into an FBE.
    """
    ensure_hotel_room_invoices_schema(conn)
    layout = get_hotel_rooms_layout(conn)
    count = 0
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        if _normalize_hotel_room_status(room.get("status")) != "occupied":
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if not stay:
            continue
        stay = _normalize_hotel_room_stay(stay)
        for line in stay.get("folioCharges") or []:
            kind = str((line or {}).get("kind") or "").strip().lower()
            if kind not in ("restaurant_room_transfer", "bar_room_transfer"):
                continue
            if upsert_pos_room_transfer_invoice(conn, room, line):
                count += 1
    return count


def _mark_pos_room_transfer_invoice_settled(conn, invoice_number, note=""):
    """Flip a POS-transfer ledger row to settled without extra stay charges."""
    ensure_hotel_room_invoices_schema(conn)
    number = _hotel_str(invoice_number, 60)
    if not number:
        return None
    item = get_hotel_room_invoice(conn, number)
    if not item:
        return None
    if _hotel_invoice_source_value(item.get("source")) != HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        return item
    if (item.get("status") or "") == "settled" or float(
        item.get("balance_amount") or 0
    ) <= 0.009:
        return item
    room = dict(item.get("room") or {})
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    stay = dict(stay)
    amount = round(float(item.get("estimated_total") or 0), 2)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payments = list(stay.get("payments") or [])
    due = round(float(item.get("balance_amount") or amount), 2)
    if due > 0:
        payments.append(
            {
                "id": f"pay-pos-transfer-{len(payments) + 1}",
                "amount": due,
                "method": "cash",
                "note": _hotel_str(note, 200) or "Collected with room bill",
                "at": stamp,
            }
        )
    stay["payments"] = payments
    stay["invoiceNumber"] = number
    stay["invoiceGenerated"] = True
    stay = _normalize_hotel_room_stay(stay)
    stay["invoiceNumber"] = number
    room["stay"] = stay
    payload = {}
    try:
        row = conn.execute(
            "SELECT payload_json FROM hotel_room_invoices WHERE invoice_number = ?",
            (number,),
        ).fetchone()
        payload = json.loads((row["payload_json"] if row else "") or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["stay"] = stay
    payload["source"] = HOTEL_INVOICE_SOURCE_POS_TRANSFER
    conn.execute(
        """
        UPDATE hotel_room_invoices
        SET advance_paid = ?,
            balance_amount = 0,
            status = 'settled',
            payload_json = ?,
            updated_at = datetime('now','localtime')
        WHERE invoice_number = ?
        """,
        (
            amount,
            json.dumps(payload, separators=(",", ":")),
            number,
        ),
    )
    return get_hotel_room_invoice(conn, number)


def sync_pos_room_transfer_invoices_for_stay(conn, room):
    """Link legacy per-POS ledger rows to the stay invoice; F&B settlement uses FBE."""
    if not isinstance(room, dict):
        return
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return
    stay = _normalize_hotel_room_stay(stay)
    if stay.get("fbTransferInvoiceGenerated") and stay.get("fbTransferInvoiceNumber"):
        _hotel_sync_all_invoice_rows(conn, room)
        return
    stay_invoice = _hotel_str(
        stay.get("invoiceNumber") or stay.get("invoice_number"), 60
    )
    for line in stay.get("folioCharges") or []:
        if not _hotel_folio_is_fb_transfer(line):
            continue
        order_no = _hotel_str(line.get("orderNo") or line.get("order_no"), 60)
        if not order_no or not stay_invoice:
            continue
        conn.execute(
            """
            UPDATE hotel_room_invoices
            SET payload_json = json_set(
                COALESCE(NULLIF(payload_json, ''), '{}'),
                '$.stayInvoiceNumber',
                ?,
                '$.posOrderNo',
                ?
            )
            WHERE source = ?
              AND (
                invoice_number = ?
                OR lower(trim(COALESCE(json_extract(payload_json, '$.posOrderNo'), '')))
                   = lower(?)
              )
            """,
            (
                stay_invoice,
                order_no,
                HOTEL_INVOICE_SOURCE_POS_TRANSFER,
                order_no,
                order_no,
            ),
        )
        if line.get("settled"):
            ledger_no = _pos_room_transfer_ledger_invoice_number(conn, order_no) or order_no
            _mark_pos_room_transfer_invoice_settled(
                conn,
                ledger_no,
                note="Collected with F&B transfer invoice",
            )


def import_hotel_room_invoice_snapshot(conn, room):
    """Upsert a historical invoice from a room+stay snapshot (no live layout merge).

    Used by room-sales migration so archived multi-room labels are preserved
    exactly as provided, without reading or changing the floor board.

    Does **not** run ``_normalize_hotel_room_stay`` (that would inflate nights via
    overstay against today's date for past check-outs).
    """
    if not isinstance(room, dict):
        return None
    room = dict(room)
    stay_in = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay_in:
        return None
    stay = dict(stay_in)
    invoice_number = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    if not invoice_number:
        return None
    ensure_hotel_room_invoices_schema(conn)

    def _money(value):
        try:
            return round(float(value or 0), 2)
        except (TypeError, ValueError):
            return 0.0

    estimated = _money(stay.get("estimatedTotal") or stay.get("estimated_total"))
    advance = _money(stay.get("advancePaid") or stay.get("advance_paid"))
    balance = _money(stay.get("balanceAmount") or stay.get("balance_amount"))
    status = _hotel_invoice_status(balance)
    generated_at = _hotel_str(
        stay.get("invoiceGeneratedAt") or stay.get("invoice_generated_at"), 40
    ) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stay["invoiceNumber"] = invoice_number
    stay["invoiceGenerated"] = True
    stay["invoiceGeneratedAt"] = generated_at
    stay["estimatedTotal"] = estimated
    stay["advancePaid"] = advance
    stay["balanceAmount"] = balance
    stay["guestName"] = _hotel_invoice_guest_name(stay) or _hotel_str(
        stay.get("guestName") or stay.get("guest_name"), 160
    )
    room_number_display = _hotel_str(
        stay.get("mergeRoomLabel") or room.get("number"), 80
    ) or _hotel_str(room.get("number"), 20)
    payload = {
        "id": room.get("id") or "",
        "number": room.get("number") or "",
        "roomType": room.get("roomType") or room.get("room_type") or "",
        "roomTypeLabel": room.get("roomTypeLabel")
        or room.get("room_type_label")
        or "",
        "floorId": room.get("floorId") or room.get("floor_id") or "",
        "status": room.get("status") or "checked_out",
        "mergeRoomNumbers": list(stay.get("mergeRoomNumbers") or []),
        "mergeRoomLabel": stay.get("mergeRoomLabel") or "",
        "importedFrom": room.get("importedFrom") or "room_sales_xlsx",
        "stay": stay,
    }
    blob = json.dumps(payload, separators=(",", ":"))
    existing = conn.execute(
        "SELECT invoice_number FROM hotel_room_invoices WHERE invoice_number = ?",
        (invoice_number,),
    ).fetchone()
    conn.execute(
        """
        INSERT INTO hotel_room_invoices (
            invoice_number, room_id, room_number, room_type_label,
            guest_name, booking_number, check_in_date, check_out_date,
            invoice_generated_at, estimated_total, advance_paid, balance_amount,
            status, payload_json, created_by, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(invoice_number) DO UPDATE SET
            room_id = excluded.room_id,
            room_number = excluded.room_number,
            room_type_label = excluded.room_type_label,
            guest_name = excluded.guest_name,
            booking_number = excluded.booking_number,
            check_in_date = excluded.check_in_date,
            check_out_date = excluded.check_out_date,
            invoice_generated_at = COALESCE(
                NULLIF(excluded.invoice_generated_at, ''),
                hotel_room_invoices.invoice_generated_at
            ),
            estimated_total = excluded.estimated_total,
            advance_paid = excluded.advance_paid,
            balance_amount = excluded.balance_amount,
            status = excluded.status,
            payload_json = excluded.payload_json,
            created_by = COALESCE(
                NULLIF(hotel_room_invoices.created_by, ''),
                excluded.created_by
            ),
            updated_at = datetime('now','localtime')
        WHERE hotel_room_invoices.status != 'cancelled'
        """,
        (
            invoice_number,
            _hotel_str(room.get("id"), 40),
            room_number_display,
            _hotel_str(
                room.get("roomTypeLabel") or room.get("room_type_label"), 80
            ),
            stay["guestName"],
            _hotel_str(stay.get("bookingNumber") or stay.get("booking_number"), 40),
            _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 10),
            _hotel_str(stay.get("checkOutDate") or stay.get("check_out_date"), 10),
            generated_at,
            estimated,
            advance,
            balance,
            status,
            blob,
            _hotel_str(
                stay.get("invoiceCreatedBy") or stay.get("invoice_created_by"), 160
            ),
        ),
    )
    return {"invoice_number": invoice_number, "created": existing is None, "status": status}


def backfill_hotel_room_invoices_from_layout(conn):
    """Upsert any in-layout stays that already have invoice numbers."""
    ensure_hotel_room_invoices_schema(conn)
    layout = get_hotel_rooms_layout(conn)
    count = 0
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if not stay:
            continue
        if not (stay.get("invoiceNumber") or stay.get("invoice_number")):
            continue
        if upsert_hotel_room_invoice_from_room(conn, room):
            count += 1
    return count


def _hotel_invoice_payment_rows_from_payload(payload, *, source=""):
    """Payment rows used for ledger labels/amounts (HBE vs FBE sources)."""
    if not isinstance(payload, dict):
        return []
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
    source_key = _hotel_invoice_source_value(source or payload.get("source"))
    rows = []
    if source_key == HOTEL_INVOICE_SOURCE_FB_COMBINED:
        inv_no = _hotel_str(
            stay.get("fbTransferInvoiceNumber")
            or stay.get("fb_transfer_invoice_number")
            or stay.get("invoiceNumber")
            or stay.get("invoice_number")
            or payload.get("invoiceNumber"),
            60,
        )
        fb_payments = stay.get("fbTransferPayments") or stay.get("fb_transfer_payments") or []
        if isinstance(fb_payments, list):
            for pay in fb_payments:
                if not isinstance(pay, dict):
                    continue
                pay_inv = _hotel_str(
                    pay.get("invoiceNumber") or pay.get("invoice_number"), 60
                )
                if pay_inv and inv_no and pay_inv != inv_no:
                    continue
                rows.append(pay)
        payload_payments = payload.get("payments")
        if isinstance(payload_payments, list):
            for pay in payload_payments:
                if not isinstance(pay, dict):
                    continue
                pay_inv = _hotel_str(
                    pay.get("invoiceNumber") or pay.get("invoice_number"), 60
                )
                if pay_inv and inv_no and pay_inv != inv_no:
                    continue
                rows.append(pay)
        return rows
    payments = stay.get("payments") or payload.get("payments") or []
    if isinstance(payments, list):
        rows.extend([p for p in payments if isinstance(p, dict)])
    return rows


def _hotel_invoice_payment_methods_from_payload(payload, *, source=""):
    """Unique stay payment methods in the order they were recorded."""
    if not isinstance(payload, dict):
        return []
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
    methods = []
    seen = set()
    for pay in _hotel_invoice_payment_rows_from_payload(payload, source=source):
        try:
            amount = float(pay.get("amount") or 0)
        except (TypeError, ValueError):
            amount = 0.0
        if abs(amount) < 0.005:
            continue
        key = _normalize_hotel_payment_method(
            pay.get("method") or pay.get("payment_method") or pay.get("paymentMethod")
        )
        if not key or key in seen:
            continue
        seen.add(key)
        methods.append(key)
    if methods:
        return methods
    if _hotel_invoice_source_value(source or payload.get("source")) == HOTEL_INVOICE_SOURCE_FB_COMBINED:
        return []
    fallback = _normalize_hotel_payment_method(
        stay.get("paymentMethod") or stay.get("payment_method")
    )
    return [fallback] if fallback else []


def _hotel_invoice_payment_amounts_from_payload(payload, *, source=""):
    """Per-tender amounts for hotel invoice ledger columns."""
    return _hotel_payment_amounts_from_payments(
        _hotel_invoice_payment_rows_from_payload(payload, source=source)
    )


def _hotel_invoice_payment_mode_label(status, methods=None):
    """Ledger Payment Mode column: tenders when settled, else Un Settled."""
    status_key = _hotel_normalize_invoice_row_status(status)
    if status_key == "cancelled":
        return "Cancelled"
    if status_key == "settled":
        labels = []
        seen = set()
        for key in methods or []:
            if not key or key in seen:
                continue
            seen.add(key)
            labels.append(
                HOTEL_ROOM_PAYMENT_METHOD_LABELS.get(
                    key, str(key).replace("_", " ").title()
                )
            )
        if labels:
            return " + ".join(labels)
        return "Settled"
    return "Un Settled"


_HOTEL_FBE_INVOICE_RE = re.compile(r"(FBE/[^\s,;)]+)", re.I)


def _hotel_fb_invoice_from_cancel_reason(reason):
    match = _HOTEL_FBE_INVOICE_RE.search(str(reason or ""))
    return match.group(1).strip() if match else ""


def _hotel_pos_transfer_payment_mode_label(item, payload=None):
    """Room Transfer ledger Status: Invoice Generated (FBE/…) or pending note."""
    fb_no = _hotel_fb_invoice_from_cancel_reason((item or {}).get("cancel_reason"))
    if not fb_no and isinstance(payload, dict):
        fb_no = _hotel_str(payload.get("fbCombinedInvoiceNumber"), 60)
    if not fb_no and isinstance(payload, dict):
        stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
        fb_no = _hotel_str(
            stay.get("fbTransferInvoiceNumber") or stay.get("fb_transfer_invoice_number"),
            60,
        )
        if not fb_no:
            for line in stay.get("folioCharges") or []:
                if not isinstance(line, dict):
                    continue
                tagged = _hotel_folio_line_invoiced_no(line)
                if tagged:
                    fb_no = tagged
                    break
    return (
        f"Invoice Generated ({fb_no})"
        if fb_no
        else "Invoice yet to generate"
    )


def _hotel_pos_transfer_is_pending_generate(item):
    """True when a POS room-transfer row has not been rolled into an FBE yet."""
    if _hotel_invoice_source_value((item or {}).get("source")) != HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        return False
    label = str((item or {}).get("payment_mode_label") or "").strip()
    if label.startswith("Invoice Generated"):
        return False
    if label == "Invoice yet to generate":
        return True
    return not bool(
        _hotel_fb_invoice_from_cancel_reason((item or {}).get("cancel_reason"))
    )


def _hotel_invoice_row_to_dict(row):
    if not row:
        return None
    item = dict(row)
    item["estimated_total"] = round(float(item.get("estimated_total") or 0), 2)
    item["advance_paid"] = round(float(item.get("advance_paid") or 0), 2)
    item["balance_amount"] = round(float(item.get("balance_amount") or 0), 2)
    item["status"] = _hotel_normalize_invoice_row_status(item.get("status"))
    item["cancel_reason"] = _hotel_str(item.get("cancel_reason"), 500)
    item["cancelled_at"] = _hotel_str(item.get("cancelled_at"), 40)
    if "source" in item:
        item["source"] = _hotel_invoice_source_value(item.get("source"))
    else:
        item["source"] = HOTEL_INVOICE_SOURCE_HOTEL
    payload = {}
    payload_json = item.pop("payload_json", None)
    if payload_json is not None:
        try:
            parsed = json.loads(payload_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            parsed = {}
        if isinstance(parsed, dict):
            payload = parsed
    methods = _hotel_invoice_payment_methods_from_payload(
        payload, source=item.get("source")
    )
    item["payment_modes"] = methods
    item["payment_amounts"] = _hotel_invoice_payment_amounts_from_payload(
        payload, source=item.get("source")
    )
    if item.get("source") == HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        item["payment_mode_label"] = _hotel_pos_transfer_payment_mode_label(
            item, payload
        )
    else:
        item["payment_mode_label"] = _hotel_invoice_payment_mode_label(
            item.get("status"), methods
        )
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
    agency_name = _hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160)
    item["agency_name"] = agency_name
    item["allow_credit"] = bool(agency_name)
    item["pos_order_no"] = _hotel_str(
        payload.get("posOrderNo") or payload.get("pos_order_no"), 60
    )
    item["created_by"] = _hotel_str(item.get("created_by"), 160)
    if not item["created_by"]:
        item["created_by"] = _hotel_str(
            stay.get("invoiceCreatedBy") or stay.get("invoice_created_by"), 160
        )
    return item


def list_hotel_room_invoices(
    conn,
    *,
    q="",
    status="",
    source="",
    outlet="",
    date_from=None,
    date_to=None,
    limit=500,
):
    """List archived room invoices newest-first."""
    ensure_hotel_room_invoices_schema(conn)
    backfill_hotel_room_invoices_from_layout(conn)
    backfill_pos_room_transfer_invoices_from_layout(conn)

    clauses = []
    params = []
    status_key = str(status or "").strip().lower()
    source_key = str(source or "").strip().lower()
    is_room_transfer_source = source_key in (
        "room_transfer",
        "pos_room_transfer",
        HOTEL_INVOICE_SOURCE_POS_TRANSFER,
    )
    # Room Transfer "Un Settled" = yet to generate (FBE), not payment-open only.
    # Room Transfer "Cancelled" status filter = Invoice Generated (FBE issued).
    pending_generate_only = is_room_transfer_source and status_key == "open"
    generated_only = is_room_transfer_source and status_key == "cancelled"
    if (
        status_key in ("open", "settled", "cancelled")
        and not pending_generate_only
        and not generated_only
    ):
        clauses.append("status = ?")
        params.append(status_key)
    if source_key in ("hotel", HOTEL_INVOICE_SOURCE_HOTEL):
        clauses.append(_HOTEL_INVOICE_STAY_SOURCE_SQL)
    elif source_key in ("hotel_ledger", "ledger"):
        clauses.append(_HOTEL_INVOICE_LEDGER_SOURCE_SQL)
    elif is_room_transfer_source:
        clauses.append("source = ?")
        params.append(HOTEL_INVOICE_SOURCE_POS_TRANSFER)
    elif source_key in (
        "fb_transfer",
        "fb_combined",
        "fb_combined_transfer",
        HOTEL_INVOICE_SOURCE_FB_COMBINED,
    ):
        clauses.append("source = ?")
        params.append(HOTEL_INVOICE_SOURCE_FB_COMBINED)
    outlet_key = str(outlet or "").strip().lower()
    if outlet_key in ("bar", "restaurant"):
        clauses.append("lower(COALESCE(room_type_label, '')) = ?")
        params.append(outlet_key)
    if date_from:
        clauses.append("substr(invoice_generated_at, 1, 10) >= ?")
        params.append(str(date_from)[:10])
    if date_to:
        clauses.append("substr(invoice_generated_at, 1, 10) <= ?")
        params.append(str(date_to)[:10])
    needle = str(q or "").strip().lower()
    if needle:
        clauses.append(
            """
            (
              lower(invoice_number) LIKE ?
              OR lower(guest_name) LIKE ?
              OR lower(room_number) LIKE ?
              OR lower(booking_number) LIKE ?
              OR lower(room_type_label) LIKE ?
              OR lower(COALESCE(created_by, '')) LIKE ?
              OR lower(COALESCE(payload_json, '')) LIKE ?
            )
            """
        )
        like = f"%{needle}%"
        params.extend([like, like, like, like, like, like, like])

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    rows = conn.execute(
        f"""
        SELECT invoice_number, room_id, room_number, room_type_label,
               guest_name, booking_number, check_in_date, check_out_date,
               invoice_generated_at, estimated_total, advance_paid,
               balance_amount, status, source, payload_json, updated_at,
               cancel_reason, cancelled_at, created_by
        FROM hotel_room_invoices
        {where}
        ORDER BY invoice_generated_at DESC, invoice_number DESC
        LIMIT ?
        """,
        (*params, int(limit)),
    ).fetchall()
    items = [_hotel_invoice_row_to_dict(row) for row in rows]
    if pending_generate_only:
        items = [row for row in items if _hotel_pos_transfer_is_pending_generate(row)]
    elif generated_only:
        items = [
            row for row in items if not _hotel_pos_transfer_is_pending_generate(row)
        ]
    return items


def hotel_room_invoice_kpis(rows, *, count_cancelled_in_billed=False):
    """KPI totals for invoice ledger rows.

    count_cancelled_in_billed: Room Transfer ledger — cancelled per-POS rows
    still represent billed transfers (often superseded by FBE) and belong in the
    total transfer bill KPI. Un Settled (`open`) counts transfers still waiting
    for invoice generation (Invoice yet to generate). `generated` counts rows
    already rolled into an FBE (Invoice Generated).
    """
    total = len(rows or [])
    open_count = 0
    settled_count = 0
    generated_count = 0
    outstanding = 0.0
    amount_sum = 0.0
    stay_room_ids = {
        str(row.get("room_id") or "").strip()
        for row in (rows or [])
        if _hotel_invoice_source_value(row.get("source"))
        not in (HOTEL_INVOICE_SOURCE_POS_TRANSFER, HOTEL_INVOICE_SOURCE_FB_COMBINED)
        and str(row.get("room_id") or "").strip()
    }
    fb_room_ids = {
        str(row.get("room_id") or "").strip()
        for row in (rows or [])
        if _hotel_invoice_source_value(row.get("source")) == HOTEL_INVOICE_SOURCE_FB_COMBINED
        and str(row.get("room_id") or "").strip()
    }
    for row in rows or []:
        status_key = _hotel_normalize_invoice_row_status(row.get("status"))
        source = _hotel_invoice_source_value(row.get("source"))
        bal = float(row.get("balance_amount") or 0)
        if (
            count_cancelled_in_billed
            and source == HOTEL_INVOICE_SOURCE_POS_TRANSFER
        ):
            amount_sum += float(row.get("estimated_total") or 0)
            if _hotel_pos_transfer_is_pending_generate(row):
                open_count += 1
                room_id = str(row.get("room_id") or "").strip()
                if room_id in stay_room_ids or room_id in fb_room_ids:
                    continue
                if bal > 0.009:
                    outstanding += bal
            else:
                generated_count += 1
                if status_key == "settled" or (
                    status_key != "cancelled" and bal <= 0.009
                ):
                    settled_count += 1
            continue
        if status_key == "cancelled":
            if count_cancelled_in_billed:
                amount_sum += float(row.get("estimated_total") or 0)
            continue
        amount_sum += float(row.get("estimated_total") or 0)
        if status_key == "settled" or bal <= 0.009:
            settled_count += 1
        else:
            open_count += 1
            room_id = str(row.get("room_id") or "").strip()
            if source == HOTEL_INVOICE_SOURCE_POS_TRANSFER and (
                room_id in stay_room_ids or room_id in fb_room_ids
            ):
                continue
            outstanding += bal
    payment_totals = _empty_hotel_payment_amounts()
    for row in rows or []:
        status_key = _hotel_normalize_invoice_row_status(row.get("status"))
        if status_key == "cancelled":
            continue
        amounts = row.get("payment_amounts")
        if not isinstance(amounts, dict):
            amounts = _empty_hotel_payment_amounts()
        for key in HOTEL_LEDGER_PAYMENT_AMOUNT_KEYS:
            payment_totals[key] = round(
                payment_totals[key] + float(amounts.get(key) or 0), 2
            )
    return {
        "total": total,
        "open": open_count,
        "settled": settled_count,
        "generated": generated_count,
        "outstanding": round(outstanding, 2),
        "amount_sum": round(amount_sum, 2),
        "payment_totals": payment_totals,
    }


def aggregate_settled_invoice_totals(conn, date_from, date_to, location=None):
    """Sum settled invoice totals across Hotel / Restaurant / Bar.

    location: None or 'All' → all modules; 'Hotel' / 'Restaurant' / 'Bar' → one module.
    Returns {"total": float, "by_day": {iso_date: float}}.
    """
    ensure_hotel_room_invoices_schema(conn)
    ensure_pos_schema(conn)

    d0 = str(date_from)[:10]
    d1 = str(date_to)[:10]
    loc = str(location or "").strip()
    if loc.lower() in ("", "all"):
        loc = None

    by_day = {}
    total = 0.0

    include_hotel = loc in (None, "Hotel")
    include_restaurant = loc in (None, "Restaurant")
    include_bar = loc in (None, "Bar")

    if include_hotel:
        rows = conn.execute(
            f"""
            SELECT substr(invoice_generated_at, 1, 10) AS sales_day,
                   COALESCE(SUM(estimated_total), 0) AS amount
            FROM hotel_room_invoices
            WHERE status = 'settled'
              AND {_HOTEL_INVOICE_STAY_SOURCE_SQL}
              AND substr(invoice_generated_at, 1, 10) >= ?
              AND substr(invoice_generated_at, 1, 10) <= ?
            GROUP BY substr(invoice_generated_at, 1, 10)
            """,
            (d0, d1),
        ).fetchall()
        for row in rows:
            day = str(row["sales_day"] or "")[:10]
            if not day:
                continue
            amount = float(row["amount"] or 0)
            by_day[day] = by_day.get(day, 0.0) + amount
            total += amount

    outlets = []
    if include_restaurant:
        outlets.append(POS_OUTLET_RESTAURANT)
    if include_bar:
        outlets.append(POS_OUTLET_BAR)
    if outlets:
        placeholders = ",".join("?" for _ in outlets)
        rows = conn.execute(
            f"""
            SELECT i.order_date AS sales_day,
                   COALESCE(SUM(i.grand_total), 0) AS amount
            FROM pos_invoices i
            WHERE i.is_active = 1
              AND i.outlet IN ({placeholders})
              AND i.order_date >= ?
              AND i.order_date <= ?
              AND lower(COALESCE(i.status, 'open')) != 'cancelled'
              AND (
                    EXISTS (
                        SELECT 1 FROM pos_invoice_payments p WHERE p.invoice_id = i.id
                    )
                    OR TRIM(COALESCE(i.settled_at, '')) != ''
              )
            GROUP BY i.order_date
            """,
            (*outlets, d0, d1),
        ).fetchall()
        for row in rows:
            day = str(row["sales_day"] or "")[:10]
            if not day:
                continue
            amount = float(row["amount"] or 0)
            by_day[day] = by_day.get(day, 0.0) + amount
            total += amount

    return {
        "total": round(total, 2),
        "by_day": {day: round(amount, 2) for day, amount in by_day.items()},
    }


INVOICE_KPI_DIGITAL_METHODS = frozenset(
    {"upi", "card", "swiggy", "zomato", "bank_transfer"}
)
INVOICE_KPI_ROOM_METHODS = frozenset({"room_transfer", "room_credit", "credit"})


def _invoice_kpi_bucket_for_method(payment_method):
    """Map a tender to cash / digital / room_credit / other."""
    hotel_key = _normalize_hotel_payment_method(payment_method)
    if hotel_key == "credit":
        return "room_credit"
    key = _normalize_pos_payment_method(payment_method)
    if key is None:
        raw = str(payment_method or "").strip().lower().replace(" ", "_")
        if raw in ("room_credit", "room-credit", "credit"):
            key = "room_transfer"
        elif raw in ("bank", "bank_transfer", "neft", "rtgs", "imps"):
            key = "bank_transfer"
        else:
            key = raw
    if key == "cash":
        return "cash"
    if key in INVOICE_KPI_DIGITAL_METHODS:
        return "digital"
    if key in INVOICE_KPI_ROOM_METHODS or key in ("room_transfer", "credit"):
        return "room_credit"
    return "other"


def _hotel_payload_tender_splits(payload_json):
    """Extract cash/digital/room_credit amounts from a hotel invoice payload."""
    cash = digital = room_credit = 0.0
    try:
        payload = json.loads(payload_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return cash, digital, room_credit
    if not isinstance(payload, dict):
        return cash, digital, room_credit
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
    payments = stay.get("payments") or payload.get("payments") or []
    if isinstance(payments, list) and payments:
        for pay in payments:
            if not isinstance(pay, dict):
                continue
            amount = float(pay.get("amount") or 0)
            if abs(amount) < 0.005:
                continue
            bucket = _invoice_kpi_bucket_for_method(
                pay.get("method") or pay.get("payment_method") or pay.get("paymentMethod")
            )
            if bucket == "cash":
                cash += amount
            elif bucket == "digital":
                digital += amount
            elif bucket == "room_credit":
                room_credit += amount
        return cash, digital, room_credit

    method = stay.get("paymentMethod") or stay.get("payment_method") or ""
    advance = float(stay.get("advancePaid") or stay.get("checkInAdvancePaid") or 0)
    if advance > 0.005 and method:
        bucket = _invoice_kpi_bucket_for_method(method)
        if bucket == "cash":
            cash += advance
        elif bucket == "digital":
            digital += advance
        elif bucket == "room_credit":
            room_credit += advance
    return cash, digital, room_credit


def _hotel_payload_sales_entry_tenders(payload_json):
    """Split hotel payload payments into cash / card / upi / room_credit / bor / other."""
    cash = card = upi = room_credit = bor = other = 0.0
    try:
        payload = json.loads(payload_json or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return cash, card, upi, room_credit, bor, other
    if not isinstance(payload, dict):
        return cash, card, upi, room_credit, bor, other
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}

    def _apply(method, amount):
        nonlocal cash, card, upi, room_credit, bor, other
        amount = float(amount or 0)
        if abs(amount) < 0.005:
            return
        hotel_key = _normalize_hotel_payment_method(method)
        if hotel_key == "cash":
            cash += amount
            return
        if hotel_key == "card":
            card += amount
            return
        if hotel_key == "upi":
            upi += amount
            return
        if hotel_key == "credit":
            room_credit += amount
            return
        if hotel_key == "bor":
            bor += amount
            return
        if hotel_key == "bank_transfer":
            # Hotel sales entry has no bank row — fold into card.
            card += amount
            return
        key = _normalize_pos_payment_method(method)
        if key is None:
            raw = str(method or "").strip().lower().replace(" ", "_")
            if raw in ("room_credit", "room-credit", "credit"):
                key = "room_transfer"
            elif raw in ("bank", "bank_transfer", "neft", "rtgs", "imps"):
                key = "bank_transfer"
            elif raw in (
                "bor",
                "back_office_receipt",
                "backofficereceipt",
                "bor_receipt",
                "bill_of_receipt",
            ):
                key = "bor"
            else:
                key = raw
        if key == "cash":
            cash += amount
        elif key == "card":
            card += amount
        elif key == "upi":
            upi += amount
        elif key in ("room_transfer", "room_credit", "credit"):
            room_credit += amount
        elif key == "bor":
            bor += amount
        elif key in ("bank_transfer", "swiggy", "zomato"):
            # Hotel sales entry has no bank/online row — fold into card.
            card += amount
        else:
            other += amount

    payments = stay.get("payments") or payload.get("payments") or []
    if isinstance(payments, list) and payments:
        for pay in payments:
            if not isinstance(pay, dict):
                continue
            _apply(
                pay.get("method") or pay.get("payment_method") or pay.get("paymentMethod"),
                pay.get("amount"),
            )
        return cash, card, upi, room_credit, bor, other

    method = stay.get("paymentMethod") or stay.get("payment_method") or ""
    advance = float(stay.get("advancePaid") or stay.get("checkInAdvancePaid") or 0)
    if advance > 0.005:
        _apply(method or "cash", advance)
    return cash, card, upi, room_credit, bor, other


def hotel_sales_entry_from_invoices(conn, sales_date):
    """Build Hotel Sales Entry totals from room invoices for one day.

    Unpaid / unsettled balance is mapped to ``room_credit`` (Guest Credit), matching FO
    ledger behavior when payment mode is missing. Back Office Receipt tenders map to ``bor``.
    """
    ensure_hotel_room_invoices_schema(conn)
    day = str(sales_date)[:10]
    rows = conn.execute(
        f"""
        SELECT estimated_total, payload_json
        FROM hotel_room_invoices
        WHERE lower(COALESCE(status, '')) IN ('open', 'settled')
          AND {_HOTEL_INVOICE_STAY_SOURCE_SQL}
          AND substr(invoice_generated_at, 1, 10) = ?
        """,
        (day,),
    ).fetchall()

    total_sales = cash = card = upi = room_credit = bor = 0.0
    for row in rows:
        amount = float(row["estimated_total"] or 0)
        total_sales += amount
        h_cash, h_card, h_upi, h_room, h_bor, h_other = _hotel_payload_sales_entry_tenders(
            row["payload_json"]
        )
        cash += h_cash
        card += h_card
        upi += h_upi
        room_credit += h_room
        bor += h_bor
        # Unmapped tenders land in Guest Credit (not BOR).
        room_credit += h_other

    allocated = cash + card + upi + room_credit + bor
    remainder = round(total_sales - allocated, 2)
    if remainder > 0.005:
        room_credit += remainder

    return {
        "total_sales": round(total_sales, 2),
        "cash": round(cash, 2),
        "card": round(card, 2),
        "upi": round(upi, 2),
        "room_credit": round(room_credit, 2),
        "bor": round(bor, 2),
    }


def pos_sales_entry_from_invoices(conn, outlet, sales_date):
    """Build Restaurant/Bar Sales Entry totals from POS invoices for one day."""
    ensure_pos_schema(conn)
    outlet_key = normalize_pos_outlet(outlet)
    day = str(sales_date)[:10]

    total_row = conn.execute(
        """
        SELECT COALESCE(SUM(i.grand_total), 0) AS amount
        FROM pos_invoices i
        WHERE i.is_active = 1
          AND i.outlet = ?
          AND i.order_date = ?
          AND lower(COALESCE(i.status, 'open')) != 'cancelled'
        """,
        (outlet_key, day),
    ).fetchone()
    total_sales = float(total_row["amount"] if total_row else 0)

    pay_rows = conn.execute(
        """
        SELECT p.payment_method AS payment_method,
               COALESCE(SUM(p.amount), 0) AS amount
        FROM pos_invoice_payments p
        JOIN pos_invoices i ON i.id = p.invoice_id
        WHERE i.is_active = 1
          AND i.outlet = ?
          AND i.order_date = ?
          AND lower(COALESCE(i.status, 'open')) != 'cancelled'
        GROUP BY p.payment_method
        """,
        (outlet_key, day),
    ).fetchall()

    cash = card = upi = room_credit = online_order = 0.0
    for row in pay_rows:
        amount = float(row["amount"] or 0)
        if abs(amount) < 0.005:
            continue
        key = _normalize_pos_payment_method(row["payment_method"])
        if key == "cash":
            cash += amount
        elif key == "card":
            card += amount
        elif key == "upi":
            upi += amount
        elif key in ("room_transfer",):
            room_credit += amount
        elif key in ("swiggy", "zomato"):
            online_order += amount
        elif key == "bank_transfer":
            card += amount

    return {
        "total_sales": round(total_sales, 2),
        "cash": round(cash, 2),
        "card": round(card, 2),
        "upi": round(upi, 2),
        "room_credit": round(room_credit, 2),
        "online_order": round(online_order, 2),
    }


def _invoice_kpi_modules(location=None):
    """Return ``(include_hotel, pos_outlets)`` for invoice KPI filters."""
    if location is None:
        return True, [POS_OUTLET_RESTAURANT, POS_OUTLET_BAR]
    if isinstance(location, (list, tuple)):
        locs = {str(item or "").strip() for item in location if str(item or "").strip()}
        include_hotel = "Hotel" in locs
        outlets = []
        if "Restaurant" in locs:
            outlets.append(POS_OUTLET_RESTAURANT)
        if "Bar" in locs:
            outlets.append(POS_OUTLET_BAR)
        return include_hotel, outlets
    loc = str(location or "").strip()
    if loc.lower() in ("", "all"):
        return True, [POS_OUTLET_RESTAURANT, POS_OUTLET_BAR]
    if loc == "Hotel":
        return True, []
    if loc == "Restaurant":
        return False, [POS_OUTLET_RESTAURANT]
    if loc == "Bar":
        return False, [POS_OUTLET_BAR]
    return True, [POS_OUTLET_RESTAURANT, POS_OUTLET_BAR]


def _empty_invoice_kpi_bucket():
    return {
        "actual_sales": 0.0,
        "digital_transactions": 0.0,
        "cash": 0.0,
        "room_credit": 0.0,
        "tips": 0.0,
        "expense": 0.0,
        "difference": 0.0,
    }


def _finalize_invoice_kpi_bucket(bucket):
    actual = round(float(bucket.get("actual_sales") or 0), 2)
    cash = round(float(bucket.get("cash") or 0), 2)
    digital = round(float(bucket.get("digital_transactions") or 0), 2)
    room_credit = round(float(bucket.get("room_credit") or 0), 2)
    expense = round(float(bucket.get("expense") or 0), 2)
    return {
        "actual_sales": actual,
        "digital_transactions": digital,
        "cash": cash,
        "room_credit": room_credit,
        "tips": round(float(bucket.get("tips") or 0), 2),
        "expense": expense,
        "difference": round(actual - (cash + digital + room_credit), 2),
    }


def aggregate_invoice_sales_kpis(conn, date_from, date_to, location=None):
    """Sum invoice KPIs for a date range (settled + unsettled).

    ``location``: None/All, ``Hotel`` / ``Restaurant`` / ``Bar``, or a list of those.
    Returns keys compatible with ``_aggregate_sales_kpis``.
    ``expense`` is left at 0 — callers may overlay ``sales_update_expenses``.
    """
    ensure_hotel_room_invoices_schema(conn)
    ensure_pos_schema(conn)

    d0 = str(date_from)[:10]
    d1 = str(date_to)[:10]
    include_hotel, outlets = _invoice_kpi_modules(location)

    actual = 0.0
    cash = 0.0
    digital = 0.0
    room_credit = 0.0

    if include_hotel:
        hotel_row = conn.execute(
            f"""
            SELECT COALESCE(SUM(estimated_total), 0) AS amount
            FROM hotel_room_invoices
            WHERE lower(COALESCE(status, '')) IN ('open', 'settled')
              AND {_HOTEL_INVOICE_STAY_SOURCE_SQL}
              AND substr(invoice_generated_at, 1, 10) >= ?
              AND substr(invoice_generated_at, 1, 10) <= ?
            """,
            (d0, d1),
        ).fetchone()
        actual += float(hotel_row["amount"] if hotel_row else 0)

        hotel_payloads = conn.execute(
            f"""
            SELECT payload_json
            FROM hotel_room_invoices
            WHERE lower(COALESCE(status, '')) IN ('open', 'settled')
              AND {_HOTEL_INVOICE_STAY_SOURCE_SQL}
              AND substr(invoice_generated_at, 1, 10) >= ?
              AND substr(invoice_generated_at, 1, 10) <= ?
            """,
            (d0, d1),
        ).fetchall()
        for row in hotel_payloads:
            h_cash, h_digital, h_room = _hotel_payload_tender_splits(row["payload_json"])
            cash += h_cash
            digital += h_digital
            room_credit += h_room

    if outlets:
        placeholders = ",".join("?" for _ in outlets)
        pos_row = conn.execute(
            f"""
            SELECT COALESCE(SUM(i.grand_total), 0) AS amount
            FROM pos_invoices i
            WHERE i.is_active = 1
              AND i.outlet IN ({placeholders})
              AND i.order_date >= ?
              AND i.order_date <= ?
              AND lower(COALESCE(i.status, 'open')) != 'cancelled'
            """,
            (*outlets, d0, d1),
        ).fetchone()
        actual += float(pos_row["amount"] if pos_row else 0)

        pay_rows = conn.execute(
            f"""
            SELECT p.payment_method AS payment_method,
                   COALESCE(SUM(p.amount), 0) AS amount
            FROM pos_invoice_payments p
            JOIN pos_invoices i ON i.id = p.invoice_id
            WHERE i.is_active = 1
              AND i.outlet IN ({placeholders})
              AND i.order_date >= ?
              AND i.order_date <= ?
              AND lower(COALESCE(i.status, 'open')) != 'cancelled'
            GROUP BY p.payment_method
            """,
            (*outlets, d0, d1),
        ).fetchall()
        for row in pay_rows:
            amount = float(row["amount"] or 0)
            if abs(amount) < 0.005:
                continue
            bucket = _invoice_kpi_bucket_for_method(row["payment_method"])
            if bucket == "cash":
                cash += amount
            elif bucket == "digital":
                digital += amount
            elif bucket == "room_credit":
                room_credit += amount

    return _finalize_invoice_kpi_bucket(
        {
            "actual_sales": actual,
            "digital_transactions": digital,
            "cash": cash,
            "room_credit": room_credit,
        }
    )


def aggregate_invoice_sales_kpis_by_day(conn, date_from, date_to, location=None):
    """Daily invoice KPI buckets for sparkline / trend charts."""
    ensure_hotel_room_invoices_schema(conn)
    ensure_pos_schema(conn)

    d0 = str(date_from)[:10]
    d1 = str(date_to)[:10]
    include_hotel, outlets = _invoice_kpi_modules(location)
    by_day = {}

    def bucket_for(day):
        return by_day.setdefault(day, _empty_invoice_kpi_bucket())

    if include_hotel:
        rows = conn.execute(
            f"""
            SELECT substr(invoice_generated_at, 1, 10) AS sales_day,
                   estimated_total, payload_json
            FROM hotel_room_invoices
            WHERE lower(COALESCE(status, '')) IN ('open', 'settled')
              AND {_HOTEL_INVOICE_STAY_SOURCE_SQL}
              AND substr(invoice_generated_at, 1, 10) >= ?
              AND substr(invoice_generated_at, 1, 10) <= ?
            """,
            (d0, d1),
        ).fetchall()
        for row in rows:
            day = str(row["sales_day"] or "")[:10]
            if not day:
                continue
            bucket = bucket_for(day)
            bucket["actual_sales"] += float(row["estimated_total"] or 0)
            h_cash, h_digital, h_room = _hotel_payload_tender_splits(row["payload_json"])
            bucket["cash"] += h_cash
            bucket["digital_transactions"] += h_digital
            bucket["room_credit"] += h_room

    if outlets:
        placeholders = ",".join("?" for _ in outlets)
        rows = conn.execute(
            f"""
            SELECT i.order_date AS sales_day,
                   COALESCE(SUM(i.grand_total), 0) AS amount
            FROM pos_invoices i
            WHERE i.is_active = 1
              AND i.outlet IN ({placeholders})
              AND i.order_date >= ?
              AND i.order_date <= ?
              AND lower(COALESCE(i.status, 'open')) != 'cancelled'
            GROUP BY i.order_date
            """,
            (*outlets, d0, d1),
        ).fetchall()
        for row in rows:
            day = str(row["sales_day"] or "")[:10]
            if not day:
                continue
            bucket_for(day)["actual_sales"] += float(row["amount"] or 0)

        pay_rows = conn.execute(
            f"""
            SELECT i.order_date AS sales_day,
                   p.payment_method AS payment_method,
                   COALESCE(SUM(p.amount), 0) AS amount
            FROM pos_invoice_payments p
            JOIN pos_invoices i ON i.id = p.invoice_id
            WHERE i.is_active = 1
              AND i.outlet IN ({placeholders})
              AND i.order_date >= ?
              AND i.order_date <= ?
              AND lower(COALESCE(i.status, 'open')) != 'cancelled'
            GROUP BY i.order_date, p.payment_method
            """,
            (*outlets, d0, d1),
        ).fetchall()
        for row in pay_rows:
            day = str(row["sales_day"] or "")[:10]
            if not day:
                continue
            amount = float(row["amount"] or 0)
            if abs(amount) < 0.005:
                continue
            bucket = bucket_for(day)
            tend = _invoice_kpi_bucket_for_method(row["payment_method"])
            if tend == "cash":
                bucket["cash"] += amount
            elif tend == "digital":
                bucket["digital_transactions"] += amount
            elif tend == "room_credit":
                bucket["room_credit"] += amount

    return {
        day: _finalize_invoice_kpi_bucket(bucket) for day, bucket in by_day.items()
    }


def get_hotel_room_invoice(conn, invoice_number):
    """Return ledger row + reconstructed room payload for print/view."""
    ensure_hotel_room_invoices_schema(conn)
    number = _hotel_str(invoice_number, 60)
    if not number:
        return None
    row = conn.execute(
        """
        SELECT invoice_number, room_id, room_number, room_type_label,
               guest_name, booking_number, check_in_date, check_out_date,
               invoice_generated_at, estimated_total, advance_paid,
               balance_amount, status, source, payload_json, updated_at,
               cancel_reason, cancelled_at
        FROM hotel_room_invoices
        WHERE invoice_number = ?
        """,
        (number,),
    ).fetchone()
    if not row:
        # Room-transfer rows may be keyed by RT series while callers still pass POS order no.
        alt = _pos_room_transfer_ledger_invoice_number(conn, number)
        if alt and alt != number:
            row = conn.execute(
                """
                SELECT invoice_number, room_id, room_number, room_type_label,
                       guest_name, booking_number, check_in_date, check_out_date,
                       invoice_generated_at, estimated_total, advance_paid,
                       balance_amount, status, source, payload_json, updated_at,
                       cancel_reason, cancelled_at
                FROM hotel_room_invoices
                WHERE invoice_number = ?
                """,
                (alt,),
            ).fetchone()
    if not row:
        return None
    item = _hotel_invoice_row_to_dict(row)
    try:
        payload = json.loads(row["payload_json"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    stay = payload.get("stay") if isinstance(payload.get("stay"), dict) else {}
    merge_numbers = payload.get("mergeRoomNumbers") or stay.get("mergeRoomNumbers") or []
    if not isinstance(merge_numbers, list):
        merge_numbers = []
    merge_label = (
        payload.get("mergeRoomLabel")
        or stay.get("mergeRoomLabel")
        or ""
    )
    room = {
        "id": payload.get("id") or item.get("room_id") or "",
        "number": payload.get("number") or "",
        "roomType": payload.get("roomType") or "",
        "roomTypeLabel": payload.get("roomTypeLabel")
        or item.get("room_type_label")
        or "",
        "floorId": payload.get("floorId") or "",
        "status": payload.get("status") or "occupied",
        "mergeRoomNumbers": merge_numbers,
        "mergeRoomLabel": merge_label,
        "mergePartnerNumbers": [
            n for n in merge_numbers if str(n) != str(payload.get("number") or "")
        ],
        "mergeLabel": merge_label
        or (payload.get("number") or item.get("room_number") or ""),
        "stay": stay,
    }
    # Display label for UI when ledger column already stores "101 + 106".
    if merge_label:
        room["numberDisplay"] = merge_label
    elif item.get("room_number"):
        room["numberDisplay"] = item.get("room_number")
    item["room"] = room
    if item.get("source") != HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        payload_source = _hotel_invoice_source_value(payload.get("source"))
        if payload_source == HOTEL_INVOICE_SOURCE_POS_TRANSFER:
            item["source"] = payload_source
    return item


def cancel_hotel_room_invoice(conn, invoice_number, reason=""):
    """Cancel an unsettled hotel stay invoice and keep the number for audit.

    Clears the live stay invoice lock so a new number can be minted.
    Room-transfer (POS) invoices must be cancelled from Point of Sale.
    """
    ensure_hotel_room_invoices_schema(conn)
    item = get_hotel_room_invoice(conn, invoice_number)
    if not item:
        raise ValueError("Invoice not found.")
    if _hotel_invoice_source_value(item.get("source")) == HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        raise ValueError("Cancel restaurant or bar room-transfer bills from Point of Sale.")
    status = _hotel_normalize_invoice_row_status(item.get("status"))
    if status == "settled":
        raise ValueError("Settled invoices cannot be cancelled.")
    if status == "cancelled":
        return {"mode": "cancelled", "invoice": item}
    reason_text = " ".join(str(reason or "").split()).strip()[:500]
    if not reason_text:
        raise ValueError("Enter a reason for cancellation.")
    inv_no = _hotel_str(item.get("invoice_number"), 60)
    cancelled_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE hotel_room_invoices
        SET status = 'cancelled',
            cancel_reason = ?,
            cancelled_at = ?,
            updated_at = datetime('now','localtime')
        WHERE invoice_number = ?
        """,
        (reason_text, cancelled_at, inv_no),
    )
    room, layout = _hotel_find_live_room_for_invoice(conn, inv_no)
    if room and layout:
        if _normalize_hotel_room_status(room.get("status")) != "occupied":
            room.pop("stay", None)
        else:
            stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
            if stay:
                stay = dict(stay)
                stay["invoiceNumber"] = ""
                stay["invoiceGenerated"] = False
                stay["invoiceGeneratedAt"] = ""
                stay["invoiceEditOpen"] = False
                room["stay"] = _normalize_hotel_room_stay(stay)
        save_hotel_rooms_layout(conn, layout.get("floors") or [], layout.get("rooms") or [])
    return {"mode": "cancelled", "invoice": get_hotel_room_invoice(conn, inv_no)}


def reopen_hotel_room_invoice_for_edit(conn, invoice_number):
    """Unlock an unsettled hotel invoice so charges can be edited again.

    Keeps the same invoice number. Generate Invoice after edits re-locks it.
    Ledger edits stay on the archived payload; live room is updated only when
    the same in-house stay still owns the invoice number.
    """
    ensure_hotel_room_invoices_schema(conn)
    item = get_hotel_room_invoice(conn, invoice_number)
    if not item:
        raise ValueError("Invoice not found.")
    if _hotel_invoice_source_value(item.get("source")) == HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        raise ValueError("Edit restaurant or bar room-transfer bills from Point of Sale.")
    status = _hotel_normalize_invoice_row_status(item.get("status"))
    if status == "settled":
        raise ValueError("Settled invoices cannot be edited.")
    if status == "cancelled":
        raise ValueError("Cancelled invoices cannot be edited.")
    inv_no = _hotel_str(item.get("invoice_number"), 60)
    conflict = _hotel_invoice_room_conflict_message(conn, item, inv_no)
    if conflict:
        raise ValueError(conflict)

    archived_room = dict(item.get("room") or {})
    stay = dict(archived_room.get("stay") if isinstance(archived_room.get("stay"), dict) else {})
    stay = _hotel_ensure_folio_charge_ids(stay)
    stay["invoiceNumber"] = inv_no
    stay["invoiceEditOpen"] = True
    stay["invoiceGenerated"] = True
    archived_room["stay"] = _normalize_hotel_room_stay(stay)
    if not archived_room.get("id"):
        archived_room["id"] = _hotel_str(item.get("room_id"), 40)
    if not archived_room.get("number"):
        archived_room["number"] = _hotel_str(item.get("room_number"), 20)
    upsert_hotel_room_invoice_from_room(conn, archived_room)

    live_room, layout = _hotel_find_live_room_for_invoice(conn, inv_no)
    if live_room:
        stay = dict(live_room.get("stay") if isinstance(live_room.get("stay"), dict) else {})
        stay["invoiceNumber"] = inv_no
        stay["invoiceEditOpen"] = True
        stay["invoiceGenerated"] = True
        live_room["stay"] = _normalize_hotel_room_stay(stay)
        rooms = list(layout.get("rooms") or [])
        room_id = str(live_room.get("id") or "")
        for idx, candidate in enumerate(rooms):
            if str(candidate.get("id") or "") == room_id:
                rooms[idx] = live_room
                break
        save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
        refreshed_live = get_hotel_room(conn, live_room.get("id"))
        _hotel_sync_live_invoice_row(conn, refreshed_live or live_room)

    refreshed_item = get_hotel_room_invoice(conn, inv_no) or item
    return {
        "invoice": refreshed_item,
        "room": (refreshed_item.get("room") if refreshed_item else archived_room),
    }


def apply_hotel_invoice_ledger_edit(conn, invoice_number, action, data=None):
    """Apply charge/discount/regenerate actions to a ledger invoice edit session."""
    ensure_hotel_room_invoices_schema(conn)
    data = data if isinstance(data, dict) else {}
    item = get_hotel_room_invoice(conn, invoice_number)
    if not item:
        raise ValueError("Invoice not found.")
    if _hotel_invoice_source_value(item.get("source")) == HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        raise ValueError("Edit restaurant or bar room-transfer bills from Point of Sale.")
    status = _hotel_normalize_invoice_row_status(item.get("status"))
    if status == "settled":
        raise ValueError("Settled invoices cannot be edited.")
    if status == "cancelled":
        raise ValueError("Cancelled invoices cannot be edited.")
    inv_no = _hotel_str(item.get("invoice_number"), 60)
    room_id = _hotel_str(item.get("room_id") or (item.get("room") or {}).get("id"), 40)
    action = str(action or "").strip().lower()

    if action == "generate_invoice":
        _hotel_require_invoice_edit_open(item)
        archived_room = dict(item.get("room") or {})
        if _hotel_invoice_has_live_stay(conn, item, inv_no) and room_id:
            live_room = get_hotel_room(conn, room_id)
            if not live_room or not isinstance(live_room.get("stay"), dict):
                raise ValueError("Invoice stay is no longer available on this room.")
            stay = dict(live_room.get("stay") or {})
            stay["invoiceNumber"] = inv_no
            stay["invoiceGenerated"] = True
            stay["invoiceEditOpen"] = False
            if not stay.get("invoiceGeneratedAt"):
                stay["invoiceGeneratedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            stay["hotelInvoicedBillableNights"] = max(
                1, int(_hotel_num(stay.get("billableNights"), 1))
            )
            stay["hotelInvoicedEstimatedTotal"] = round(
                float(stay.get("estimatedTotal") or 0), 2
            )
            stay["hotelInvoicedExtraBedAmount"] = round(
                float(stay.get("extraBedAmount") or 0), 2
            )
            stay["hotelInvoicedEarlyCheckinAmount"] = round(
                float(stay.get("earlyCheckinAmount") or 0), 2
            )
            stay["hotelInvoicedLateCheckoutAmount"] = round(
                float(stay.get("lateCheckoutAmount") or 0), 2
            )
            stay = _normalize_hotel_room_stay(stay)
            live_room = dict(live_room)
            live_room["stay"] = stay
            layout = get_hotel_rooms_layout(conn)
            rooms = list(layout.get("rooms") or [])
            for idx, candidate in enumerate(rooms):
                if str(candidate.get("id") or "") == str(room_id):
                    rooms[idx] = live_room
                    break
            save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
            upsert_hotel_room_invoice_from_room(conn, live_room)
            refreshed_live = get_hotel_room(conn, room_id)
            _hotel_sync_live_invoice_row(conn, refreshed_live or live_room)
            refreshed = get_hotel_room_invoice(conn, inv_no)
            return {
                "room": refreshed_live
                or (refreshed.get("room") if refreshed else live_room),
                "minted": False,
                "invoice": refreshed,
            }
        stay = dict(archived_room.get("stay") if isinstance(archived_room.get("stay"), dict) else {})
        stay["invoiceEditOpen"] = False
        stay["invoiceGenerated"] = True
        if not stay.get("invoiceGeneratedAt"):
            stay["invoiceGeneratedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        stay["hotelInvoicedBillableNights"] = max(
            1, int(_hotel_num(stay.get("billableNights"), 1))
        )
        stay["hotelInvoicedEstimatedTotal"] = round(
            float(stay.get("estimatedTotal") or 0), 2
        )
        stay["hotelInvoicedExtraBedAmount"] = round(
            float(stay.get("extraBedAmount") or 0), 2
        )
        stay["hotelInvoicedEarlyCheckinAmount"] = round(
            float(stay.get("earlyCheckinAmount") or 0), 2
        )
        stay["hotelInvoicedLateCheckoutAmount"] = round(
            float(stay.get("lateCheckoutAmount") or 0), 2
        )
        archived_room["stay"] = _normalize_hotel_room_stay(stay)
        upsert_hotel_room_invoice_from_room(conn, archived_room)
        refreshed = get_hotel_room_invoice(conn, inv_no)
        return {
            "room": (refreshed.get("room") if refreshed else archived_room),
            "minted": False,
            "invoice": refreshed,
        }

    archived_room = dict(_hotel_require_invoice_edit_open(item))
    if not archived_room.get("id"):
        archived_room["id"] = room_id
    stay = archived_room.get("stay") if isinstance(archived_room.get("stay"), dict) else {}

    if action == "update_charge":
        if _hotel_invoice_has_live_stay(conn, item, inv_no) and room_id:
            result = update_hotel_room_charge(
                conn,
                room_id,
                charge_key=data.get("chargeKey") or data.get("charge_key") or data.get("key") or "",
                label=data.get("label") or data.get("name") or "",
                amount=data.get("amount"),
                rate=data.get("rate"),
            )
            refreshed = get_hotel_room_invoice(conn, inv_no)
            return {"room": result.get("room") or (refreshed.get("room") if refreshed else archived_room), "invoice": refreshed}
        stay = _hotel_mutate_stay_charge(
            stay,
            room_id,
            data.get("chargeKey") or data.get("charge_key") or data.get("key") or "",
            label=data.get("label") or data.get("name") or "",
            amount=data.get("amount"),
            rate=data.get("rate"),
        )
    elif action == "delete_charge":
        if _hotel_invoice_has_live_stay(conn, item, inv_no) and room_id:
            result = delete_hotel_room_charge(
                conn,
                room_id,
                charge_key=data.get("chargeKey") or data.get("charge_key") or data.get("key") or "",
            )
            refreshed = get_hotel_room_invoice(conn, inv_no)
            return {"room": result.get("room") or (refreshed.get("room") if refreshed else archived_room), "invoice": refreshed}
        stay = _hotel_delete_stay_charge(
            stay,
            data.get("chargeKey") or data.get("charge_key") or data.get("key") or "",
        )
    elif action == "set_discount":
        if _hotel_invoice_has_live_stay(conn, item, inv_no) and room_id:
            result = set_hotel_room_discount(
                conn,
                room_id,
                discount_type=data.get("discountType") or data.get("discount_type") or "pct",
                discount_value=data.get("discountValue")
                if data.get("discountValue") is not None
                else data.get("discount_value"),
                discount_reason=data.get("discountReason") or data.get("discount_reason") or "",
            )
            refreshed = get_hotel_room_invoice(conn, inv_no)
            return {"room": result.get("room") or (refreshed.get("room") if refreshed else archived_room), "invoice": refreshed}
        stay = _hotel_apply_stay_discount(
            stay,
            discount_type=data.get("discountType") or data.get("discount_type") or "pct",
            discount_value=data.get("discountValue")
            if data.get("discountValue") is not None
            else data.get("discount_value"),
            discount_reason=data.get("discountReason") or data.get("discount_reason") or "",
        )
    elif action == "add_custom_charge":
        if _hotel_invoice_has_live_stay(conn, item, inv_no) and room_id:
            result = append_hotel_room_folio_charge(
                conn,
                room_id,
                amount=data.get("amount") if data.get("amount") is not None else data.get("rate"),
                kind="other",
                label=data.get("label") or data.get("name") or data.get("chargeName") or data.get("charge_name") or "",
                source="hotel_invoice",
                note=data.get("note") or data.get("notes") or "",
            )
            refreshed = get_hotel_room_invoice(conn, inv_no)
            return {
                "room": result.get("room") or (refreshed.get("room") if refreshed else archived_room),
                "charge": result.get("charge"),
                "invoice": refreshed,
            }
        stay, charge = _hotel_append_stay_folio_charge(
            stay,
            room_id,
            amount=data.get("amount") if data.get("amount") is not None else data.get("rate"),
            kind="other",
            label=data.get("label") or data.get("name") or data.get("chargeName") or data.get("charge_name") or "",
            source="hotel_invoice",
            note=data.get("note") or data.get("notes") or "",
        )
        archived_room["stay"] = stay
        room_out = _hotel_persist_archived_invoice_edit(conn, item, archived_room)
        refreshed = get_hotel_room_invoice(conn, inv_no)
        return {"room": room_out, "charge": charge, "invoice": refreshed}
    elif action == "record_payment":
        return record_hotel_room_invoice_payment(
            conn,
            inv_no,
            payment=data.get("payment"),
            payment_splits=data.get("payment_splits") or data.get("paymentSplits"),
            note=data.get("note") or data.get("notes") or "",
        )
    else:
        raise ValueError("Unsupported invoice edit action.")

    archived_room["stay"] = stay
    room_out = _hotel_persist_archived_invoice_edit(conn, item, archived_room)
    refreshed = get_hotel_room_invoice(conn, inv_no)
    return {"room": room_out, "invoice": refreshed}


def _normalize_hotel_payment_method(value):
    key = str(value or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("bank", "banktransfer", "neft", "rtgs", "imps"):
        key = "bank_transfer"
    if key in ("agent_credit", "agency_credit", "on_credit"):
        key = "credit"
    if key in (
        "back_office_receipt",
        "backofficereceipt",
        "bor_receipt",
        "bill_of_receipt",
    ):
        key = "bor"
    if key not in HOTEL_ROOM_PAYMENT_METHODS:
        return ""
    return key


def _hotel_bor_agency_name(stay_or_item):
    if not isinstance(stay_or_item, dict):
        return ""
    stay = stay_or_item.get("stay") if isinstance(stay_or_item.get("stay"), dict) else stay_or_item
    if not isinstance(stay, dict):
        stay = stay_or_item
    return _hotel_str(
        stay.get("agencyName")
        or stay.get("agency_name")
        or stay_or_item.get("agency_name")
        or stay_or_item.get("agencyName"),
        160,
    )


def _validate_and_consume_hotel_bor_splits(conn, splits, *, agency_name: str, invoice_number: str):
    """Validate BOR receipt_id rows and write allocations for this invoice settle."""
    from back_office_receipt import (
        insert_back_office_receipt_invoice_allocations,
        list_pending_back_office_receipts_for_agency,
    )

    bor_rows = [s for s in (splits or []) if (s.get("method") or "") == "bor"]
    if not bor_rows:
        return
    if not agency_name:
        raise ValueError(
            "Back Office Receipt is only allowed when an agency is on this stay."
        )
    pending = {
        int(item["id"]): item
        for item in list_pending_back_office_receipts_for_agency(
            conn, agency_name=agency_name
        )
    }
    applied_this = {}
    allocations = []
    for split in bor_rows:
        try:
            receipt_id = int(split.get("receipt_id") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Select a Back Office Receipt for the BOR payment.") from exc
        if receipt_id <= 0:
            raise ValueError("Select a Back Office Receipt for the BOR payment.")
        amount = round(float(split.get("amount") or 0), 2)
        item = pending.get(receipt_id)
        if not item:
            raise ValueError(
                "One or more Back Office Receipts are not available for this agency."
            )
        used = applied_this.get(receipt_id, 0.0)
        remaining = round(float(item["pending_amount"]) - used, 2)
        if amount - remaining > 0.009:
            raise ValueError(
                f"{item['receipt_no']} apply ₹{amount:.2f} exceeds pending ₹{remaining:.2f}."
            )
        applied_this[receipt_id] = round(used + amount, 2)
        allocations.append({"receipt_id": receipt_id, "amount": amount})
    insert_back_office_receipt_invoice_allocations(conn, invoice_number, allocations)

def _hotel_flag_value(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _hotel_stay_flag_if_present(stay, camel, snake):
    if not isinstance(stay, dict):
        return None
    if camel in stay:
        return _hotel_flag_value(stay.get(camel))
    if snake in stay:
        return _hotel_flag_value(stay.get(snake))
    return None


def _hotel_stay_agency_bill_flags(stay):
    """Return (room, fb) agency-billing flags; legacy agencyBilling sets both."""
    if not isinstance(stay, dict):
        return False, False
    room = _hotel_stay_flag_if_present(stay, "agencyRoomBilling", "agency_room_billing")
    fb = _hotel_stay_flag_if_present(stay, "agencyFbBilling", "agency_fb_billing")
    if room is not None or fb is not None:
        return bool(room), bool(fb)
    legacy = _hotel_stay_flag_if_present(stay, "agencyBilling", "agency_billing")
    on = bool(legacy)
    return on, on


def _hotel_stay_bills_room_to_agency(stay):
    room, _fb = _hotel_stay_agency_bill_flags(stay)
    return bool(room and _hotel_stay_has_agency(stay))


def _hotel_stay_bills_fb_to_agency(stay):
    _room, fb = _hotel_stay_agency_bill_flags(stay)
    return bool(fb and _hotel_stay_has_agency(stay))


def _hotel_validate_agency_billing(stay):
    room, fb = _hotel_stay_agency_bill_flags(stay)
    if (room or fb) and not _hotel_stay_has_agency(stay):
        raise ValueError("Agency Name is required for Agency Billing.")


def _hotel_stay_has_agency(stay):
    """True when an agency/agent is attached to the stay (enables Credit pay)."""
    if not isinstance(stay, dict):
        return False
    name = _hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160)
    return bool(name)


def _hotel_invoice_allow_credit(conn, item):
    """Whether Credit pay is allowed for a ledger invoice (archived or live stay agency)."""
    if not isinstance(item, dict):
        return False
    room = dict(item.get("room") or {})
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    if _hotel_stay_has_agency(stay):
        return True
    room_id = _hotel_str(item.get("room_id") or room.get("id"), 40)
    if not room_id:
        return False
    live = get_hotel_room(conn, room_id)
    if not live or _normalize_hotel_room_status(live.get("status")) != "occupied":
        return False
    live_stay = live.get("stay") if isinstance(live.get("stay"), dict) else None
    return bool(live_stay and _hotel_stay_has_agency(live_stay))



def _hotel_floor_id_for_number(number):
    digits = re.sub(r"\D", "", str(number or ""))
    if not digits:
        return "floor-1"
    return f"floor-{digits[0]}"


def default_hotel_rooms_layout():
    """Build the seeded 3-floor / 20-room board from the spreadsheet inventory."""
    floors = [
        {"id": "floor-1", "name": "Floor 1"},
        {"id": "floor-2", "name": "Floor 2"},
        {"id": "floor-3", "name": "Floor 3"},
    ]
    rooms = []
    for number, type_key in _HOTEL_ROOMS_SEED_SPEC:
        rooms.append(
            {
                "id": f"room-{number}",
                "number": str(number),
                "floorId": _hotel_floor_id_for_number(number),
                "roomType": type_key,
                "roomTypeLabel": HOTEL_ROOM_TYPE_LABELS.get(type_key, type_key),
                "status": "vacant",
            }
        )
    return {"floors": floors, "rooms": rooms}


def _normalize_hotel_room_status(status):
    key = str(status or "").strip().lower().replace(" ", "_").replace("-", "_")
    if key in ("ooo", "out_of_service", "oos"):
        key = "out_of_order"
    if key in ("available", "free", "clean"):
        key = "vacant"
    if key not in HOTEL_ROOM_STATUSES:
        return "vacant"
    return key


def _hotel_room_is_merge_linked(room):
    """True when the room is (or still looks like) part of a billing merge group."""
    if not isinstance(room, dict):
        return False
    if str(room.get("mergeGroupId") or "").strip():
        return True
    if room.get("mergePrimary"):
        return True
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    role = str(stay.get("mergeRole") or "").strip().lower()
    if role in ("member", "primary"):
        return True
    if str(stay.get("billingRoomId") or room.get("billingRoomId") or "").strip():
        return True
    return False


def _hotel_room_has_inhouse_stay(room):
    """True when the room still has an in-house guest stay (not a bare reservation)."""
    if not isinstance(room, dict):
        return False
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return False
    status = _normalize_hotel_room_status(room.get("status"))
    # Explicit reservation inventory is not in-house yet.
    if status == "reserved":
        return False
    if stay.get("checkedInAt") or stay.get("checked_in_at"):
        return True
    # Copied party identity on a merged peer is not occupancy.
    if _hotel_room_is_merge_linked(room):
        return status == "occupied"
    guest = _hotel_str(
        stay.get("guestName")
        or stay.get("guest_name")
        or " ".join(
            p
            for p in (
                stay.get("firstName") or stay.get("first_name") or "",
                stay.get("lastName") or stay.get("last_name") or "",
            )
            if p
        ),
        160,
    )
    check_in = _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 10)
    if guest and check_in:
        return True
    if guest and (stay.get("folioCharges") or stay.get("payments")):
        return True
    # Merge role alone is not in-house — empty shells must not look Occupied.
    return False


_HOTEL_MERGE_SHARED_GUEST_KEYS = (
    "title",
    "firstName",
    "lastName",
    "guestName",
    "gender",
    "dateOfBirth",
    "nationality",
    "mobileCountry",
    "mobile",
    "email",
    "address",
    "city",
    "state",
    "country",
    "pin",
    "purposeOfVisit",
    "vipStatus",
    "returningGuest",
    "idType",
    "idNumber",
    "idIssueDate",
    "idExpiryDate",
    "idPlaceOfIssue",
    "idDocumentName",
    "idDocumentPath",
    "idDocumentMime",
    "idDocumentStoredName",
    "profession",
    "company",
    "loyaltyNumber",
    "notes",
    "checkInDate",
    "checkInTime",
    "checkOutDate",
    "checkOutTime",
    "nights",
    "adults",
    "children",
    "bookingNumber",
    "bookingDate",
    "reservationId",
    "reservationBookingId",
    "specialRequests",
    "additionalRequests",
    "additionalGuests",
)

_HOTEL_MERGE_SHARED_AGENCY_KEYS = (
    "agencyName",
    "agencyGst",
    "agencyAddress",
    "agencyBilling",
    "agencyRoomBilling",
    "agencyFbBilling",
    "invoiceTo",
    "billingName",
)

_HOTEL_MERGE_SHARED_BILL_KEYS = (
    "ratePlan",
    "roomRate",
    "totalRate",
    "paymentMethod",
    "advancePaid",
    "checkInAdvancePaid",
    "paymentReference",
    "balanceAmount",
    "invoiceNumber",
    "invoiceGenerated",
    "invoiceGeneratedAt",
    "invoiceEditOpen",
    "invoiceHistory",
    "payments",
    "extraBedQty",
    "extraBedRate",
    "extraBedNights",
    "extraBedAmount",
    "extraBedNote",
    "earlyCheckinQty",
    "earlyCheckinRate",
    "earlyCheckinNights",
    "earlyCheckinAmount",
    "earlyCheckinNote",
    "lateCheckoutQty",
    "lateCheckoutRate",
    "lateCheckoutNights",
    "lateCheckoutAmount",
    "lateCheckoutNote",
    "folioCharges",
    "discountType",
    "discountValue",
    "discountAmount",
    "discountReason",
    "estimatedTotal",
    "hotelInvoicedBillableNights",
    "hotelInvoicedEstimatedTotal",
    "hotelInvoicedExtraBedAmount",
    "hotelInvoicedEarlyCheckinAmount",
    "hotelInvoicedLateCheckoutAmount",
    "fbTransferInvoiceNumber",
    "fbTransferInvoiceGenerated",
    "fbTransferInvoiceGeneratedAt",
    "fbTransferTotal",
    "fbTransferBalance",
    "fbTransferPayments",
)


def _hotel_stay_has_guest_name(stay):
    """True when the stay already has a displayable guest identity."""
    if not isinstance(stay, dict):
        return False
    if _hotel_str(stay.get("guestName") or stay.get("guest_name"), 160):
        return True
    if _hotel_str(stay.get("firstName") or stay.get("first_name"), 80):
        return True
    if _hotel_str(stay.get("lastName") or stay.get("last_name"), 80):
        return True
    return False


def _hotel_stay_guest_richness(stay):
    if not isinstance(stay, dict):
        return 0
    score = 0
    if stay.get("guestName") or stay.get("firstName") or stay.get("lastName"):
        score += 20
    if stay.get("mobile"):
        score += 8
    if stay.get("checkInDate") or stay.get("check_in_date"):
        score += 8
    if stay.get("checkedInAt") or stay.get("checked_in_at"):
        score += 6
    if stay.get("bookingNumber") or stay.get("booking_number"):
        score += 4
    if stay.get("email"):
        score += 2
    folio = stay.get("folioCharges") or []
    if isinstance(folio, list) and folio:
        score += 10
    try:
        if float(stay.get("roomRate") or 0) > 0:
            score += 5
    except (TypeError, ValueError):
        pass
    try:
        if float(stay.get("estimatedTotal") or 0) > 0:
            score += 5
    except (TypeError, ValueError):
        pass
    return score


def _hotel_copy_stay_fields(dest, source, keys):
    if not isinstance(dest, dict) or not isinstance(source, dict):
        return dest
    for key in keys:
        val = source.get(key)
        # Skip empties and False so overlay never wipes member billed* / bool locks.
        if val in (None, "", [], {}, False):
            continue
        dest[key] = val
    return dest


def _hotel_lock_invoiced_snapshots_to_current(stay):
    """Align hotelInvoiced* with current billable totals on an already-minted stay.

    Used when a merge successor inherits the primary bill after checkout so the UI
    does not invent a false 'Generate Additional Room Invoice' from date overstay.
    """
    if not isinstance(stay, dict):
        return stay
    inv = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    if not inv or not (
        stay.get("invoiceGenerated")
        if "invoiceGenerated" in stay
        else stay.get("invoice_generated")
    ):
        return stay
    out = dict(stay)
    out["hotelInvoicedBillableNights"] = max(
        1, int(_hotel_num(out.get("billableNights"), 1))
    )
    try:
        out["hotelInvoicedEstimatedTotal"] = round(float(out.get("estimatedTotal") or 0), 2)
    except (TypeError, ValueError):
        out["hotelInvoicedEstimatedTotal"] = 0.0
    for src, dest in (
        ("extraBedAmount", "hotelInvoicedExtraBedAmount"),
        ("earlyCheckinAmount", "hotelInvoicedEarlyCheckinAmount"),
        ("lateCheckoutAmount", "hotelInvoicedLateCheckoutAmount"),
    ):
        try:
            out[dest] = round(float(out.get(src) or 0), 2)
        except (TypeError, ValueError):
            out[dest] = 0.0
    return out


def _hotel_upsert_merge_rate_rows(existing_rows, incoming_rows):
    """Merge incoming mergeRoomRates into existing rows by roomId / number."""
    out = []
    index_by_id = {}
    index_by_num = {}
    for row in existing_rows or []:
        if not isinstance(row, dict):
            continue
        copy = dict(row)
        out.append(copy)
        rid = str(copy.get("roomId") or "").strip()
        num = str(copy.get("number") or "").strip()
        if rid:
            index_by_id[rid] = len(out) - 1
        if num:
            index_by_num[num] = len(out) - 1
    for row in incoming_rows or []:
        if not isinstance(row, dict):
            continue
        rid = str(row.get("roomId") or "").strip()
        num = str(row.get("number") or "").strip()
        idx = None
        if rid and rid in index_by_id:
            idx = index_by_id[rid]
        elif num and num in index_by_num:
            idx = index_by_num[num]
        if idx is None:
            copy = dict(row)
            out.append(copy)
            if rid:
                index_by_id[rid] = len(out) - 1
            if num:
                index_by_num[num] = len(out) - 1
            continue
        merged = dict(out[idx])
        for key, value in row.items():
            if key == "nightlyRates":
                if isinstance(value, list) and value:
                    merged["nightlyRates"] = list(value)
                continue
            if value in (None, "", [], {}):
                continue
            merged[key] = value
        # Prefer explicit roomRate / first nightly when provided.
        try:
            rate = float(row.get("roomRate")) if row.get("roomRate") is not None else None
        except (TypeError, ValueError):
            rate = None
        if rate is not None:
            merged["roomRate"] = max(0.0, rate)
            nightly = merged.get("nightlyRates")
            if isinstance(nightly, list) and nightly and isinstance(nightly[0], dict):
                first = dict(nightly[0])
                first["roomRate"] = merged["roomRate"]
                if row.get("ratePlan"):
                    first["ratePlan"] = row.get("ratePlan")
                nightly = list(nightly)
                nightly[0] = first
                merged["nightlyRates"] = nightly
        out[idx] = merged
    return out


def _hotel_sync_merge_group_shared_data(rooms, tariff_rates=None, rate_source_room_id=None):
    """Keep bill money on the primary; do not overwrite each room's own guest.

    Folio/payments stay on the billing primary; members keep mergeRole and
    billingRoomId. Occupancy, checkedInAt, and guest identity stay on each
    room. Empty merge shells still inherit the primary guest for display.

    rate_source_room_id: when set (check-in/edit save), only that room's
    mergeRoomRates are folded onto the primary so sibling edits don't clobber.
    """
    if not isinstance(rooms, list):
        return
    groups = {}
    for room in rooms:
        if not isinstance(room, dict):
            continue
        gid = str(room.get("mergeGroupId") or "").strip()
        if not gid:
            continue
        groups.setdefault(gid, []).append(room)

    for peers in groups.values():
        if len(peers) < 2:
            continue
        primary = next((r for r in peers if r.get("mergePrimary")), None)
        if not primary:
            primary = peers[0]
            primary["mergePrimary"] = True
        source = max(
            peers,
            key=lambda r: (
                _hotel_stay_guest_richness(r.get("stay")),
                1 if r.get("id") == primary.get("id") else 0,
            ),
        )
        source_stay = source.get("stay") if isinstance(source.get("stay"), dict) else {}
        primary_stay = (
            dict(primary.get("stay"))
            if isinstance(primary.get("stay"), dict)
            else {}
        )
        if not _hotel_stay_has_guest_name(primary_stay):
            _hotel_copy_stay_fields(
                primary_stay, source_stay, _HOTEL_MERGE_SHARED_GUEST_KEYS
            )
        if not _hotel_str(primary_stay.get("agencyName") or primary_stay.get("agency_name"), 160):
            _hotel_copy_stay_fields(
                primary_stay, source_stay, _HOTEL_MERGE_SHARED_AGENCY_KEYS
            )
        # If the richest stay was a member that still held money (pre-absorb),
        # fold bill fields onto primary when primary is empty.
        if (
            _hotel_stay_guest_richness(source_stay)
            and source.get("id") != primary.get("id")
        ):
            primary_has_folio = bool(primary_stay.get("folioCharges"))
            source_has_folio = bool(source_stay.get("folioCharges"))
            try:
                primary_rate = float(primary_stay.get("roomRate") or 0)
            except (TypeError, ValueError):
                primary_rate = 0.0
            try:
                source_rate = float(source_stay.get("roomRate") or 0)
            except (TypeError, ValueError):
                source_rate = 0.0
            if not primary_has_folio and source_has_folio:
                _hotel_copy_stay_fields(
                    primary_stay, source_stay, _HOTEL_MERGE_SHARED_BILL_KEYS
                )
            elif primary_rate <= 0 and source_rate > 0:
                for key in ("roomRate", "totalRate", "nights", "ratePlan"):
                    if not primary_stay.get(key) and source_stay.get(key) not in (
                        None,
                        "",
                        [],
                        {},
                    ):
                        primary_stay[key] = source_stay.get(key)
        primary_stay["mergeRole"] = "primary"
        primary_stay["billingRoomId"] = ""
        primary["stay"] = primary_stay
        primary["mergePrimary"] = True

        for room in peers:
            if room.get("id") == primary.get("id"):
                continue
            member_stay = (
                dict(room.get("stay"))
                if isinstance(room.get("stay"), dict)
                else {}
            )
            own_checked_in = member_stay.get("checkedInAt") or member_stay.get(
                "checked_in_at"
            )
            member_has_guest = _hotel_stay_has_guest_name(member_stay)
            if not member_has_guest:
                _hotel_copy_stay_fields(
                    member_stay, primary_stay, _HOTEL_MERGE_SHARED_GUEST_KEYS
                )
            _hotel_copy_stay_fields(
                member_stay, primary_stay, _HOTEL_MERGE_SHARED_AGENCY_KEYS
            )
            member_stay["mergeRole"] = "member"
            member_stay["billingRoomId"] = str(primary.get("id") or "")
            # Occupancy timestamp stays on the room that actually checked in.
            if own_checked_in:
                member_stay["checkedInAt"] = own_checked_in
            else:
                member_stay.pop("checkedInAt", None)
                member_stay.pop("checked_in_at", None)
            # Empty shells get display-only rate/nights; money stays on primary.
            if not member_has_guest:
                for key in ("roomRate", "nights", "ratePlan", "adults", "children"):
                    if primary_stay.get(key) not in (None, "", [], {}):
                        member_stay[key] = primary_stay.get(key)
            room["stay"] = member_stay
            room["mergePrimary"] = False
            room["mergeGroupId"] = primary.get("mergeGroupId")

        # Fold rate edits only when a specific room was just saved. Layout heal /
        # merge (rate_source_room_id=None) must not re-apply stale member
        # mergeRoomRates and clobber the primary bill.
        folded_rates = list(primary_stay.get("mergeRoomRates") or [])
        source_id = str(rate_source_room_id or "").strip()
        if source_id:
            for room in peers:
                rid = str(room.get("id") or "").strip()
                if rid and rid != source_id and rid != str(primary.get("id") or ""):
                    continue
                mstay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
                peer_rows = mstay.get("mergeRoomRates") or []
                if isinstance(peer_rows, list) and peer_rows:
                    folded_rates = _hotel_upsert_merge_rate_rows(folded_rates, peer_rows)
            primary_stay["mergeRoomRates"] = folded_rates
            primary["stay"] = primary_stay

        _hotel_sync_merged_room_rate_folio(
            primary, rooms, tariff_rates=tariff_rates
        )

        # Members read mergeRoomRates via overlay — clear stored copies so a later
        # heal cannot re-fold stale partial lists onto the primary.
        primary_rates = list((primary.get("stay") or {}).get("mergeRoomRates") or [])
        for room in peers:
            if room.get("id") == primary.get("id"):
                continue
            mstay = room.get("stay") if isinstance(room.get("stay"), dict) else None
            if not isinstance(mstay, dict):
                continue
            if mstay.get("mergeRoomRates"):
                mstay = dict(mstay)
                mstay["mergeRoomRates"] = []
                room["stay"] = mstay
        if primary_rates and isinstance(primary.get("stay"), dict):
            primary["stay"]["mergeRoomRates"] = primary_rates


def _hotel_overlay_merge_shared_bill_view(room, rooms):
    """API/UI helper: members see the primary's folio, totals, and agency.

    Guest identity is copied from the primary only when this room has no name.
    """
    if not isinstance(room, dict):
        return room
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    is_member = bool(
        room.get("isMergeMember")
        or stay.get("mergeRole") == "member"
        or stay.get("billingRoomId")
    )
    if not is_member:
        return room
    group_id = str(room.get("mergeGroupId") or "").strip()
    primary = None
    billing_id = str(stay.get("billingRoomId") or room.get("billingRoomId") or "").strip()
    for peer in rooms or []:
        if not isinstance(peer, dict):
            continue
        if billing_id and (
            peer.get("id") == billing_id or peer.get("number") == billing_id
        ):
            primary = peer
            break
        if group_id and str(peer.get("mergeGroupId") or "").strip() == group_id and peer.get(
            "mergePrimary"
        ):
            primary = peer
            break
    if not primary:
        return room
    pstay = primary.get("stay") if isinstance(primary.get("stay"), dict) else {}
    if not pstay:
        return room
    view = dict(stay)
    own_checked_in = view.get("checkedInAt") or view.get("checked_in_at")
    if not _hotel_stay_has_guest_name(view):
        _hotel_copy_stay_fields(view, pstay, _HOTEL_MERGE_SHARED_GUEST_KEYS)
    _hotel_copy_stay_fields(view, pstay, _HOTEL_MERGE_SHARED_AGENCY_KEYS)
    _hotel_copy_stay_fields(view, pstay, _HOTEL_MERGE_SHARED_BILL_KEYS)
    if isinstance(pstay.get("mergeRoomRates"), list):
        view["mergeRoomRates"] = list(pstay.get("mergeRoomRates") or [])
    view["mergeRole"] = "member"
    view["billingRoomId"] = str(primary.get("id") or billing_id)
    if own_checked_in:
        view["checkedInAt"] = own_checked_in
    else:
        view.pop("checkedInAt", None)
        view.pop("checked_in_at", None)
    room["stay"] = view
    return room


def _hotel_heal_merge_group_occupancy(rooms, tariff_rates=None):
    """Restore Occupied only for rooms that themselves have an in-house stay.

    Merge groups share billing, not occupancy or guest identity. A vacant or
    reserved peer must not flip to Occupied because another room checked in.
    Empty merge shells (no guest on any peer) must not display as Occupied.
    """
    if not isinstance(rooms, list):
        return
    # 1) Orphan stay with vacant/dirty inventory → occupied when truly in-house;
    #    otherwise drop cancelled reservation shells so vacant rooms stay bookable.
    #    Merge-linked shells keep their stay even when not in-house.
    for room in rooms:
        if not isinstance(room, dict):
            continue
        status = _normalize_hotel_room_status(room.get("status"))
        if status not in ("vacant", "dirty"):
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if not stay:
            continue
        if stay.get("invoiceEditOpen") or stay.get("invoice_edit_open"):
            continue
        if _hotel_room_has_inhouse_stay(room):
            room["status"] = "occupied"
        elif _hotel_room_is_merge_linked(room):
            continue
        else:
            room.pop("stay", None)

    # 2) Merge groups: keep links; do not occupy peers together.
    groups = {}
    for room in rooms:
        if not isinstance(room, dict):
            continue
        gid = str(room.get("mergeGroupId") or "").strip()
        if not gid:
            continue
        groups.setdefault(gid, []).append(room)
    for peers in groups.values():
        primary = next((r for r in peers if r.get("mergePrimary")), None)
        # Orphan members (primary unmerged with scope=one) stay hidden on the
        # board via isMergeMember — dissolve invalid / singleton groups.
        if primary is None or len(peers) < 2:
            for room in peers:
                stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
                if stay:
                    stay = dict(stay)
                    stay["billingRoomId"] = ""
                    stay["mergeRole"] = ""
                    room["stay"] = _normalize_hotel_room_stay(stay)
                _hotel_clear_room_merge_fields(room)
            continue
        has_guest = any(
            _hotel_stay_guest_richness(r.get("stay")) > 0 or _hotel_room_has_inhouse_stay(r)
            for r in peers
        )
        if has_guest:
            for room in peers:
                stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
                stay = dict(stay)
                if room.get("mergePrimary") or (
                    primary and room.get("id") == primary.get("id")
                ):
                    stay["mergeRole"] = "primary"
                    stay["billingRoomId"] = ""
                else:
                    stay["mergeRole"] = "member"
                    stay["billingRoomId"] = str((primary or {}).get("id") or "")
                room["stay"] = stay
        else:
            # Linked rooms with no guest — keep merge, drop false Occupied
            for room in peers:
                if _normalize_hotel_room_status(room.get("status")) != "occupied":
                    continue
                if _hotel_room_has_inhouse_stay(room):
                    continue
                if _hotel_stay_guest_richness(room.get("stay")) > 0:
                    continue
                room["status"] = "vacant"

    # 2b) Member flags without a merge group id (board would still hide them)
    for room in rooms:
        if not isinstance(room, dict):
            continue
        if str(room.get("mergeGroupId") or "").strip():
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if not stay:
            continue
        role = str(stay.get("mergeRole") or "").strip().lower()
        billing = str(stay.get("billingRoomId") or "").strip()
        if role != "member" and not billing:
            continue
        stay = dict(stay)
        stay["billingRoomId"] = ""
        stay["mergeRole"] = ""
        room["stay"] = _normalize_hotel_room_stay(stay)

    # 3) Shared billing; keep each room's own guest when present
    _hotel_sync_merge_group_shared_data(rooms, tariff_rates=tariff_rates)


def _normalize_hotel_rooms_payload(floors, rooms, tax_rates=None, tariff_rates=None):
    """Sanitize floors/rooms lists into a stable layout payload."""
    # Pass the full slab blob through so each stay can pick ≤ / > threshold rates.
    rates = tax_rates if isinstance(tax_rates, dict) else _hotel_tax_rates_or_default(None)
    norm_floors = []
    seen_floor = set()
    if isinstance(floors, list):
        for idx, raw in enumerate(floors):
            if not isinstance(raw, dict):
                continue
            fid = str(raw.get("id") or "").strip() or f"floor-{idx + 1}"
            if fid in seen_floor:
                continue
            seen_floor.add(fid)
            name = str(raw.get("name") or fid).strip() or fid
            norm_floors.append({"id": fid, "name": name})
    if not norm_floors:
        norm_floors = [
            {"id": "floor-1", "name": "Floor 1"},
            {"id": "floor-2", "name": "Floor 2"},
            {"id": "floor-3", "name": "Floor 3"},
        ]

    floor_ids = {f["id"] for f in norm_floors}
    norm_rooms = []
    seen_room = set()
    if isinstance(rooms, list):
        for raw in rooms:
            if not isinstance(raw, dict):
                continue
            number = str(raw.get("number") or "").strip()
            if not number:
                continue
            rid = str(raw.get("id") or "").strip() or f"room-{number}"
            if rid in seen_room:
                continue
            seen_room.add(rid)
            floor_id = str(raw.get("floorId") or "").strip() or _hotel_floor_id_for_number(number)
            if floor_id not in floor_ids:
                floor_id = _hotel_floor_id_for_number(number)
                if floor_id not in floor_ids:
                    floor_id = norm_floors[0]["id"]
            type_key = str(raw.get("roomType") or "").strip() or "premium_deluxe_balcony"
            type_label = HOTEL_ROOM_TYPE_LABELS.get(type_key) or str(
                raw.get("roomTypeLabel") or ""
            ).strip()
            if not type_label:
                type_label = type_key
            room_obj = {
                "id": rid,
                "number": number,
                "floorId": floor_id,
                "roomType": type_key,
                "roomTypeLabel": type_label,
                "status": _normalize_hotel_room_status(raw.get("status")),
            }
            merge_group_id = str(raw.get("mergeGroupId") or raw.get("merge_group_id") or "").strip()
            if merge_group_id:
                room_obj["mergeGroupId"] = merge_group_id[:60]
                room_obj["mergePrimary"] = bool(
                    raw.get("mergePrimary")
                    if "mergePrimary" in raw
                    else raw.get("merge_primary")
                )
            stay = raw.get("stay")
            if isinstance(stay, dict) and stay:
                room_obj["stay"] = _normalize_hotel_room_stay(stay, tax_rates=rates)
            upcoming = raw.get("upcomingStay")
            if not isinstance(upcoming, dict):
                upcoming = raw.get("upcoming_stay")
            if isinstance(upcoming, dict) and upcoming:
                room_obj["upcomingStay"] = _normalize_hotel_room_stay(
                    upcoming, tax_rates=rates
                )
            norm_rooms.append(room_obj)
    _hotel_heal_merge_group_occupancy(norm_rooms, tariff_rates=tariff_rates)
    norm_rooms.sort(key=lambda r: (r["floorId"], r["number"]))
    return {"floors": norm_floors, "rooms": norm_rooms}


def hotel_rooms_status_counts(layout, *, as_of=None):
    """KPI counts for the rooms board.

    expected_checkout = occupied rooms whose expected check-out date
    matches as_of (defaults to today). Each physical room counts, including
    merge-group members.
    """
    rooms = (layout or {}).get("rooms") or []
    counts = {key: 0 for key in HOTEL_ROOM_STATUSES}
    counts["total"] = 0
    counts["expected_checkout"] = 0
    day = str(as_of or date.today().isoformat())[:10]
    for room in rooms:
        if not isinstance(room, dict):
            continue
        counts["total"] += 1
        status = _normalize_hotel_room_status(room.get("status"))
        counts[status] = counts.get(status, 0) + 1
        if status != "occupied":
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
        checkout = str(
            stay.get("checkOutDate")
            or stay.get("check_out_date")
            or stay.get("expectedCheckOut")
            or ""
        )[:10]
        if checkout == day:
            counts["expected_checkout"] += 1
    return counts


def _hotel_merge_occupancy_drift(raw_rooms, healed_rooms):
    """True when heal/sync changed status or shared guest fields vs stored payload."""
    if not isinstance(raw_rooms, list) or not isinstance(healed_rooms, list):
        return False
    raw_by_id = {
        str(r.get("id") or ""): r
        for r in raw_rooms
        if isinstance(r, dict) and r.get("id")
    }
    for healed in healed_rooms:
        if not isinstance(healed, dict):
            continue
        raw = raw_by_id.get(str(healed.get("id") or ""))
        if not raw:
            continue
        if _normalize_hotel_room_status(raw.get("status")) != _normalize_hotel_room_status(
            healed.get("status")
        ):
            return True
        if str(raw.get("mergeGroupId") or "") != str(healed.get("mergeGroupId") or ""):
            return True
        if bool(raw.get("mergePrimary")) != bool(healed.get("mergePrimary")):
            return True
        hstay = healed.get("stay") if isinstance(healed.get("stay"), dict) else {}
        rstay = raw.get("stay") if isinstance(raw.get("stay"), dict) else {}
        for key in (
            "guestName",
            "firstName",
            "lastName",
            "mobile",
            "email",
            "checkInDate",
            "bookingNumber",
            "mergeRole",
            "billingRoomId",
            "estimatedTotal",
        ):
            if (hstay.get(key) or "") != (rstay.get(key) or ""):
                return True
        h_rates = hstay.get("mergeRoomRates") or []
        r_rates = rstay.get("mergeRoomRates") or []
        if len(h_rates) != len(r_rates):
            return True
        for idx, hrow in enumerate(h_rates):
            if not isinstance(hrow, dict):
                continue
            rrow = r_rates[idx] if idx < len(r_rates) else {}
            if not isinstance(rrow, dict):
                return True
            try:
                if abs(float(hrow.get("roomRate") or 0) - float(rrow.get("roomRate") or 0)) > 0.009:
                    return True
            except (TypeError, ValueError):
                return True
        h_folio = [
            f
            for f in (hstay.get("folioCharges") or [])
            if isinstance(f, dict)
            and str(f.get("source") or "") in ("merged_room_rate", "room_merge")
        ]
        r_folio = [
            f
            for f in (rstay.get("folioCharges") or [])
            if isinstance(f, dict)
            and str(f.get("source") or "") in ("merged_room_rate", "room_merge")
        ]
        if len(h_folio) != len(r_folio):
            return True
        h_by_src = {str(f.get("sourceRoomId") or ""): f for f in h_folio}
        for rf in r_folio:
            hf = h_by_src.get(str(rf.get("sourceRoomId") or ""))
            if not hf:
                return True
            try:
                if abs(float(hf.get("amount") or 0) - float(rf.get("amount") or 0)) > 0.009:
                    return True
            except (TypeError, ValueError):
                return True
    return False


def get_hotel_rooms_layout(conn):
    """Load hotel rooms layout JSON; seed 20 rooms when empty."""
    ensure_hotel_rooms_schema(conn)
    rates = get_hotel_tax_rates(conn)
    tariffs = get_hotel_tariff_rates(conn)
    row = conn.execute(
        "SELECT payload FROM hotel_rooms_layout WHERE id = 1"
    ).fetchone()
    if not row:
        payload = default_hotel_rooms_layout()
        save_hotel_rooms_layout(conn, payload.get("floors"), payload.get("rooms"))
        return _normalize_hotel_rooms_payload(
            payload.get("floors"),
            payload.get("rooms"),
            tax_rates=rates,
            tariff_rates=tariffs,
        )
    try:
        parsed = json.loads(row["payload"] or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    floors = parsed.get("floors")
    rooms = parsed.get("rooms")
    if not isinstance(floors, list) or not isinstance(rooms, list) or not rooms:
        payload = default_hotel_rooms_layout()
        save_hotel_rooms_layout(conn, payload.get("floors"), payload.get("rooms"))
        return _normalize_hotel_rooms_payload(
            payload.get("floors"),
            payload.get("rooms"),
            tax_rates=rates,
            tariff_rates=tariffs,
        )
    layout = _normalize_hotel_rooms_payload(
        floors, rooms, tax_rates=rates, tariff_rates=tariffs
    )
    if _hotel_merge_occupancy_drift(rooms, layout.get("rooms") or []):
        layout = save_hotel_rooms_layout(
            conn, layout.get("floors") or [], layout.get("rooms") or []
        )
    return layout


def save_hotel_rooms_layout(conn, floors, rooms):
    """Replace hotel rooms layout payload (singleton row)."""
    ensure_hotel_rooms_schema(conn)
    rates = get_hotel_tax_rates(conn)
    tariffs = get_hotel_tariff_rates(conn)
    existing_row = conn.execute(
        "SELECT payload FROM hotel_rooms_layout WHERE id = 1"
    ).fetchone()
    if existing_row:
        try:
            existing = json.loads(existing_row["payload"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            existing = {}
        if isinstance(existing, dict) and isinstance(existing.get("rooms"), list):
            existing_by_id = {
                str(r.get("id") or ""): r
                for r in existing["rooms"]
                if isinstance(r, dict) and r.get("id")
            }
            new_ids = set()
            for r in rooms or []:
                if not isinstance(r, dict):
                    continue
                number = str(r.get("number") or "").strip()
                if not number:
                    continue
                new_ids.add(str(r.get("id") or "").strip() or f"room-{number}")
            for rid, prev in existing_by_id.items():
                if rid in new_ids:
                    continue
                status = _normalize_hotel_room_status(prev.get("status"))
                if status in ("occupied", "reserved"):
                    raise ValueError(
                        f"Cannot remove room {prev.get('number') or rid} while it is {status}."
                    )
    payload = _normalize_hotel_rooms_payload(
        floors, rooms, tax_rates=rates, tariff_rates=tariffs
    )
    blob = json.dumps(payload, separators=(",", ":"))
    conn.execute(
        f"""
        INSERT INTO hotel_rooms_layout (id, payload, updated_at)
        VALUES (1, ?, {SQL_NOW})
        ON CONFLICT(id) DO UPDATE SET
            payload = excluded.payload,
            updated_at = {SQL_NOW}
        """,
        (blob,),
    )
    return payload


def _hotel_str(value, max_len=200):
    return str(value or "").strip()[:max_len]


def _hotel_num(value, default=0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


_HOTEL_ID_DOC_NAME_RE = re.compile(
    r"^(?:"
    r"[A-Za-z0-9._-]+\.(webp|pdf|jpe?g|png|heic|heif)"
    r"|[0-9a-f]{32}"
    r"|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    r")$",
    re.IGNORECASE,
)


def _hotel_id_document_basename(value):
    text = str(value or "").strip().replace("\\", "/")
    text = text.split("?")[0].split("#")[0].rstrip("/")
    if text.endswith("/raw") or text.endswith("/content"):
        text = text.rsplit("/", 1)[0]
    if "/" in text:
        text = text.split("/")[-1]
    if not text or ".." in text:
        return ""
    if _HOTEL_ID_DOC_NAME_RE.match(text):
        return text
    return ""


def _hotel_id_document_view_path(name, path):
    stored = _hotel_id_document_basename(path) or _hotel_id_document_basename(name)
    if not stored:
        return _hotel_str(path, 200)
    return "/hotel/api/id-documents/view/" + stored + "/raw"


_HOTEL_TITLE_RE = re.compile(
    r"^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?\s+(.+)$", re.IGNORECASE
)
_HOTEL_TITLE_ONLY_RE = re.compile(
    r"^(Mr|Mrs|Ms|Miss|Dr|Mx)\.?$", re.IGNORECASE
)
_HOTEL_TITLE_MAP = {
    "mr": "Mr",
    "mrs": "Mrs",
    "ms": "Ms",
    "miss": "Ms",
    "dr": "Dr",
    "mx": "Mx",
}


def _hotel_normalize_title_token(value):
    text = str(value or "").strip()
    m = _HOTEL_TITLE_ONLY_RE.match(text)
    if not m:
        return ""
    return _HOTEL_TITLE_MAP.get(m.group(1).lower(), "")


def _hotel_split_guest_name(guest_name):
    """Split guest display name into title / first / last (honorifics are not first names)."""
    text = _hotel_str(guest_name, 160)
    title = ""
    if not text:
        return "", "", ""
    m = _HOTEL_TITLE_RE.match(text)
    if m:
        title = _HOTEL_TITLE_MAP.get(m.group(1).lower(), "")
        text = (m.group(2) or "").strip()
    else:
        only = _hotel_normalize_title_token(text)
        if only:
            return only, "", ""
    parts = text.split() if text else []
    first = parts[0] if parts else ""
    last = " ".join(parts[1:]) if len(parts) > 1 else ""
    return title, first, last


def _hotel_parse_iso_date(value):
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _hotel_night_date_list(check_in, nights, overstay_nights=0):
    """Calendar dates for each billable night (check-in night through last night)."""
    in_date = _hotel_parse_iso_date(check_in)
    if in_date is None:
        return []
    try:
        booked = max(1, int(nights or 1))
    except (TypeError, ValueError):
        booked = 1
    try:
        overstay = max(0, int(overstay_nights or 0))
    except (TypeError, ValueError):
        overstay = 0
    total = booked + overstay
    return [(in_date + timedelta(days=i)).isoformat() for i in range(total)]


def _hotel_normalize_nightly_rates(
    raw,
    *,
    check_in,
    nights,
    overstay_nights=0,
    default_rate=0.0,
    default_plan="",
):
    """Build ordered nightlyRates aligned to the stay window.

    Missing nights are filled from the previous night (or defaults). Extra
    overstay nights append using the last night's rate/plan.
    """
    try:
        default_rate = max(0.0, float(default_rate or 0))
    except (TypeError, ValueError):
        default_rate = 0.0
    default_plan = _hotel_str(default_plan, 20)
    dates = _hotel_night_date_list(check_in, nights, overstay_nights)
    if not dates:
        # No check-in date — keep any well-formed rows as-is (capped).
        cleaned = []
        if isinstance(raw, list):
            for item in raw[:60]:
                if not isinstance(item, dict):
                    continue
                day = _hotel_str(item.get("date"), 20)
                if not day or _hotel_parse_iso_date(day) is None:
                    continue
                try:
                    rate = round(max(0.0, float(item.get("roomRate") or item.get("room_rate") or 0)), 2)
                except (TypeError, ValueError):
                    rate = round(default_rate, 2)
                plan = (
                    _hotel_str(item.get("ratePlan") or item.get("rate_plan") or default_plan, 20)
                    or default_plan
                )
                cleaned.append({"date": day, "roomRate": rate, "ratePlan": plan})
        return cleaned

    by_date = {}
    if isinstance(raw, list):
        for item in raw:
            if not isinstance(item, dict):
                continue
            day = _hotel_str(item.get("date"), 20)
            if not day or _hotel_parse_iso_date(day) is None:
                continue
            try:
                rate = round(max(0.0, float(item.get("roomRate") or item.get("room_rate") or 0)), 2)
            except (TypeError, ValueError):
                rate = None
            plan = _hotel_str(item.get("ratePlan") or item.get("rate_plan"), 20)
            by_date[day] = {"roomRate": rate, "ratePlan": plan or None}

    out_rows = []
    prev_rate = round(default_rate, 2)
    prev_plan = default_plan
    for day in dates:
        existing = by_date.get(day) or {}
        rate = existing.get("roomRate")
        plan = existing.get("ratePlan")
        if rate is None:
            rate = prev_rate
        if not plan:
            plan = prev_plan
        rate = round(max(0.0, float(rate)), 2)
        plan = _hotel_str(plan or default_plan, 20) or default_plan
        out_rows.append({"date": day, "roomRate": rate, "ratePlan": plan})
        prev_rate = rate
        prev_plan = plan
    return out_rows


def _hotel_sum_nightly_rates(nightly_rates):
    if not isinstance(nightly_rates, list) or not nightly_rates:
        return None
    total = 0.0
    for item in nightly_rates:
        if not isinstance(item, dict):
            continue
        try:
            total += max(0.0, float(item.get("roomRate") or 0))
        except (TypeError, ValueError):
            continue
    return round(total, 2)


def _hotel_stay_room_charges_amount(stay, billable_nights=None):
    """Room tariff total: sum(nightlyRates) or roomRate × billable nights."""
    stay = stay if isinstance(stay, dict) else {}
    nightly = stay.get("nightlyRates") or stay.get("nightly_rates")
    summed = _hotel_sum_nightly_rates(nightly)
    if summed is not None:
        return summed
    try:
        rate = max(0.0, float(stay.get("roomRate") or stay.get("room_rate") or 0))
    except (TypeError, ValueError):
        rate = 0.0
    if billable_nights is None:
        try:
            nights = max(1, int(float(stay.get("nights") or 1)))
        except (TypeError, ValueError):
            nights = 1
        overstay = _hotel_overstay_extra_nights(stay)
        billable_nights = max(1, nights + overstay)
    try:
        billable = max(1, int(billable_nights or 1))
    except (TypeError, ValueError):
        billable = 1
    return round(rate * billable, 2)


def _hotel_overstay_extra_nights(stay, as_of=None):
    """Extra billable nights after expected check-out while guest is still in-house.

    Expected check-out on Aug 1 and still in-house on Aug 2 → 1 night.
    Each further calendar day past expected check-out adds another night.
    """
    if not isinstance(stay, dict):
        return 0
    out_date = _hotel_parse_iso_date(
        stay.get("checkOutDate")
        or stay.get("check_out_date")
        or stay.get("expectedCheckOut")
    )
    if out_date is None:
        in_date = _hotel_parse_iso_date(
            stay.get("checkInDate") or stay.get("check_in_date")
        )
        try:
            booked = max(1, int(float(stay.get("nights") or 1)))
        except (TypeError, ValueError):
            booked = 1
        if in_date is not None:
            out_date = in_date + timedelta(days=booked)
    if out_date is None:
        return 0
    if as_of is None:
        as_of_date = datetime.now().date()
    elif hasattr(as_of, "date") and callable(as_of.date):
        as_of_date = as_of.date()
    else:
        as_of_date = _hotel_parse_iso_date(as_of) or datetime.now().date()
    if as_of_date <= out_date:
        return 0
    return (as_of_date - out_date).days


def _hotel_stay_independent_billing(stay):
    """True when this stay opted out of shared/reservation auto-merge billing."""
    if not isinstance(stay, dict):
        return False
    val = stay.get("independentBilling")
    if val is None:
        val = stay.get("independent_billing")
    if isinstance(val, bool):
        return val
    return str(val or "").strip().lower() in ("1", "true", "yes", "on")


def _normalize_hotel_room_stay(stay, tax_rates=None):
    """Sanitize guest/booking payload stored on a room."""
    if not isinstance(stay, dict):
        return {}
    special = stay.get("specialRequests") or stay.get("special_requests") or []
    if isinstance(special, str):
        special = [s.strip() for s in special.split(",") if s.strip()]
    if not isinstance(special, list):
        special = []
    special = [_hotel_str(s, 40) for s in special if _hotel_str(s, 40)][:20]

    def _num(value, default=0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    adults = int(_num(stay.get("adults"), 1) or 1)
    children = int(_num(stay.get("children"), 0) or 0)
    nights = int(_num(stay.get("nights"), 1) or 1)
    room_rate = round(_num(stay.get("roomRate") or stay.get("room_rate"), 0), 2)
    advance = round(_num(stay.get("advancePaid") or stay.get("advance_paid"), 0), 2)
    total_rate = stay.get("totalRate") or stay.get("total_rate")
    total_rate = round(_num(total_rate, room_rate * nights), 2)
    # balance recomputed after folio/extras below
    balance = 0.0

    title = _hotel_str(stay.get("title"), 20)
    first = _hotel_str(stay.get("firstName") or stay.get("first_name"), 80)
    last = _hotel_str(stay.get("lastName") or stay.get("last_name"), 80)
    guest_name = _hotel_str(stay.get("guestName") or stay.get("guest_name"), 160)
    first_as_title = _hotel_normalize_title_token(first)
    if first_as_title:
        title = title or first_as_title
        first = ""
    if guest_name and not (first or last):
        title_from_name, first, last = _hotel_split_guest_name(guest_name)
        if title_from_name and not title:
            title = title_from_name
    elif first_as_title and last:
        _t2, f2, l2 = _hotel_split_guest_name(last)
        first = f2 or last
        last = l2 or first
    if not guest_name:
        guest_name = " ".join(p for p in (title, first, last) if p).strip()

    room_bill, fb_bill = _hotel_stay_agency_bill_flags(stay)

    out = {
        "bookingNumber": _hotel_str(
            stay.get("bookingNumber") or stay.get("booking_number"), 40
        ),
        "reservationId": _hotel_str(
            stay.get("reservationId")
            or stay.get("reservation_id")
            or stay.get("providerReservationId")
            or stay.get("provider_reservation_id"),
            80,
        ),
        "reservationBookingId": _hotel_str(
            stay.get("reservationBookingId")
            or stay.get("reservation_booking_id")
            or stay.get("bookingId")
            or stay.get("booking_id"),
            80,
        ),
        "bookingDate": _hotel_str(stay.get("bookingDate") or stay.get("booking_date"), 20),
        "title": title,
        "firstName": first,
        "lastName": last,
        "guestName": guest_name,
        "gender": _hotel_str(stay.get("gender"), 20),
        "dateOfBirth": _hotel_str(stay.get("dateOfBirth") or stay.get("date_of_birth"), 20),
        "nationality": _hotel_str(stay.get("nationality"), 60),
        "mobileCountry": _hotel_str(stay.get("mobileCountry") or stay.get("mobile_country"), 8)
        or "+91",
        "mobile": _hotel_str(stay.get("mobile"), 30),
        "email": _hotel_str(stay.get("email"), 120),
        "address": _hotel_str(stay.get("address"), 300),
        "city": _hotel_str(stay.get("city"), 80),
        "state": _hotel_str(stay.get("state"), 80),
        "country": _hotel_str(stay.get("country"), 80),
        "pin": _hotel_str(stay.get("pin") or stay.get("postalCode") or stay.get("postal_code"), 20),
        "purposeOfVisit": _hotel_str(
            stay.get("purposeOfVisit") or stay.get("purpose_of_visit"), 80
        ),
        "vipStatus": _hotel_str(stay.get("vipStatus") or stay.get("vip_status"), 40),
        "returningGuest": _hotel_str(
            stay.get("returningGuest") or stay.get("returning_guest"), 20
        ),
        "idType": _hotel_str(stay.get("idType") or stay.get("id_type"), 40),
        "idNumber": _hotel_str(stay.get("idNumber") or stay.get("id_number"), 160),
        "idIssueDate": _hotel_str(stay.get("idIssueDate") or stay.get("id_issue_date"), 20),
        "idExpiryDate": _hotel_str(
            stay.get("idExpiryDate") or stay.get("id_expiry_date"), 20
        ),
        "idPlaceOfIssue": _hotel_str(
            stay.get("idPlaceOfIssue") or stay.get("id_place_of_issue"), 80
        ),
        "idDocumentName": _hotel_str(
            stay.get("idDocumentName") or stay.get("id_document_name"), 120
        ),
        "idDocumentPath": _hotel_id_document_view_path(
            stay.get("idDocumentName") or stay.get("id_document_name"),
            stay.get("idDocumentPath") or stay.get("id_document_path"),
        ),
        "idDocumentMime": _hotel_str(
            stay.get("idDocumentMime") or stay.get("id_document_mime"), 60
        ),
        "idDocumentStoredName": _hotel_str(
            stay.get("idDocumentStoredName") or stay.get("id_document_stored_name"),
            120,
        ),
        "additionalGuests": [],
        "agencyName": _hotel_str(stay.get("agencyName") or stay.get("agency_name"), 160),
        "agencyGst": _hotel_str(stay.get("agencyGst") or stay.get("agency_gst"), 40),
        "agencyAddress": _hotel_str(
            stay.get("agencyAddress") or stay.get("agency_address"), 300
        ),
        "agencyRoomBilling": room_bill,
        "agencyFbBilling": fb_bill,
        "agencyBilling": bool(room_bill or fb_bill),
        "invoiceTo": _hotel_str(stay.get("invoiceTo") or stay.get("invoice_to"), 160),
        "billingName": _hotel_str(stay.get("billingName") or stay.get("billing_name"), 160),
        "profession": _hotel_str(stay.get("profession"), 80),
        "company": _hotel_str(stay.get("company"), 120),
        "loyaltyNumber": _hotel_str(
            stay.get("loyaltyNumber") or stay.get("loyalty_number"), 60
        ),
        "notes": _hotel_str(stay.get("notes"), 500),
        "checkInDate": _hotel_str(stay.get("checkInDate") or stay.get("check_in_date"), 20),
        "checkInTime": _hotel_str(stay.get("checkInTime") or stay.get("check_in_time"), 20),
        "checkOutDate": _hotel_str(
            stay.get("checkOutDate") or stay.get("check_out_date"), 20
        ),
        "checkOutTime": _hotel_str(
            stay.get("checkOutTime") or stay.get("check_out_time"), 20
        ),
        "nights": max(1, nights),
        "overstayNights": 0,
        "billableNights": max(1, nights),
        "adults": max(1, adults),
        "children": max(0, children),
        "ratePlan": _hotel_str(stay.get("ratePlan") or stay.get("rate_plan"), 60),
        "roomRate": room_rate,
        "totalRate": total_rate,
        "paymentMethod": _hotel_str(
            stay.get("paymentMethod") or stay.get("payment_method"), 40
        ),
        "advancePaid": advance,
        "checkInAdvancePaid": round(
            _num(
                stay.get("checkInAdvancePaid")
                if "checkInAdvancePaid" in stay
                else stay.get("check_in_advance_paid"),
                -1,
            ),
            2,
        ),
        "paymentReference": _hotel_str(
            stay.get("paymentReference") or stay.get("payment_reference"), 80
        ),
        "balanceAmount": balance,
        "invoiceNumber": _hotel_str(
            stay.get("invoiceNumber") or stay.get("invoice_number"), 60
        ),
        "invoiceGenerated": bool(
            stay.get("invoiceGenerated")
            if "invoiceGenerated" in stay
            else stay.get("invoice_generated")
        ),
        "invoiceGeneratedAt": _hotel_str(
            stay.get("invoiceGeneratedAt") or stay.get("invoice_generated_at"), 40
        ),
        "invoiceEditOpen": bool(
            stay.get("invoiceEditOpen")
            if "invoiceEditOpen" in stay
            else stay.get("invoice_edit_open")
        ),
        "invoiceCreatedBy": _hotel_str(
            stay.get("invoiceCreatedBy") or stay.get("invoice_created_by"), 160
        ),
        "billedInvoiceNumber": _hotel_str(
            stay.get("billedInvoiceNumber") or stay.get("billed_invoice_number"), 60
        ),
        "billedInvoiceGenerated": bool(
            stay.get("billedInvoiceGenerated")
            if "billedInvoiceGenerated" in stay
            else stay.get("billed_invoice_generated")
        ),
        "billedInvoiceGeneratedAt": _hotel_str(
            stay.get("billedInvoiceGeneratedAt")
            or stay.get("billed_invoice_generated_at"),
            40,
        ),
        "billedFbTransferInvoiceNumber": _hotel_str(
            stay.get("billedFbTransferInvoiceNumber")
            or stay.get("billed_fb_transfer_invoice_number"),
            60,
        ),
        "billedFbTransferInvoiceGenerated": bool(
            stay.get("billedFbTransferInvoiceGenerated")
            if "billedFbTransferInvoiceGenerated" in stay
            else stay.get("billed_fb_transfer_invoice_generated")
        ),
        "billedFbTransferInvoiceGeneratedAt": _hotel_str(
            stay.get("billedFbTransferInvoiceGeneratedAt")
            or stay.get("billed_fb_transfer_invoice_generated_at"),
            40,
        ),
        "payments": [],
        "specialRequests": special,
        "additionalRequests": _hotel_str(
            stay.get("additionalRequests") or stay.get("additional_requests"), 400
        ),
        "extraBedQty": max(0, int(_num(stay.get("extraBedQty") or stay.get("extra_bed_qty"), 0))),
        "extraBedRate": round(_num(stay.get("extraBedRate") or stay.get("extra_bed_rate"), 0), 2),
        "extraBedNights": max(0, int(_num(stay.get("extraBedNights") or stay.get("extra_bed_nights"), 0))),
        "extraBedAmount": round(_num(stay.get("extraBedAmount") or stay.get("extra_bed_amount"), 0), 2),
        "extraBedNote": _hotel_str(stay.get("extraBedNote") or stay.get("extra_bed_note"), 200),
        "earlyCheckinQty": max(
            0, int(_num(stay.get("earlyCheckinQty") or stay.get("early_checkin_qty"), 0))
        ),
        "earlyCheckinRate": round(
            _num(stay.get("earlyCheckinRate") or stay.get("early_checkin_rate"), 0), 2
        ),
        "earlyCheckinNights": max(
            0, int(_num(stay.get("earlyCheckinNights") or stay.get("early_checkin_nights"), 0))
        ),
        "earlyCheckinAmount": round(
            _num(stay.get("earlyCheckinAmount") or stay.get("early_checkin_amount"), 0), 2
        ),
        "earlyCheckinNote": _hotel_str(
            stay.get("earlyCheckinNote") or stay.get("early_checkin_note"), 200
        ),
        "lateCheckoutQty": max(
            0, int(_num(stay.get("lateCheckoutQty") or stay.get("late_checkout_qty"), 0))
        ),
        "lateCheckoutRate": round(
            _num(stay.get("lateCheckoutRate") or stay.get("late_checkout_rate"), 0), 2
        ),
        "lateCheckoutNights": max(
            0, int(_num(stay.get("lateCheckoutNights") or stay.get("late_checkout_nights"), 0))
        ),
        "lateCheckoutAmount": round(
            _num(stay.get("lateCheckoutAmount") or stay.get("late_checkout_amount"), 0), 2
        ),
        "lateCheckoutNote": _hotel_str(
            stay.get("lateCheckoutNote") or stay.get("late_checkout_note"), 200
        ),
        "chargeLabels": _hotel_normalize_charge_labels(
            stay.get("chargeLabels") or stay.get("charge_labels") or {}
        ),
        "folioCharges": [],
        "fbTransferTotal": 0.0,
        "fbTransferBalance": 0.0,
        "fbTransferInvoiceNumber": "",
        "fbTransferInvoiceGenerated": False,
        "fbTransferInvoiceGeneratedAt": "",
        "fbTransferPayments": [],
        "combinedBalanceDue": 0.0,
        "discountType": "pct",
        "discountValue": 0.0,
        "discountAmount": 0.0,
        "discountReason": "",
        "estimatedTotal": 0.0,
        "checkedInAt": _hotel_str(
            stay.get("checkedInAt") or stay.get("checked_in_at"), 40
        ),
        "transferCount": max(0, int(_num(stay.get("transferCount") or stay.get("transfer_count"), 0))),
        "transferHistory": [],
        "billingRoomId": _hotel_str(
            stay.get("billingRoomId") or stay.get("billing_room_id"), 40
        ),
        "mergeRole": _hotel_str(stay.get("mergeRole") or stay.get("merge_role"), 20).lower(),
        "independentBilling": _hotel_stay_independent_billing(stay),
        "mergeRoomNumbers": [],
        "mergeRoomLabel": "",
        "mergeRoomRates": [],
    }
    if out["mergeRole"] not in ("member", "primary"):
        out["mergeRole"] = "member" if out["billingRoomId"] else ""
    if out["mergeRole"] in ("member", "primary"):
        out["independentBilling"] = False
    merge_nums_raw = (
        stay.get("mergeRoomNumbers")
        or stay.get("merge_room_numbers")
        or []
    )
    merge_numbers = []
    if isinstance(merge_nums_raw, (list, tuple)):
        for item in merge_nums_raw[:20]:
            num = _hotel_str(item, 20)
            if num and num not in merge_numbers:
                merge_numbers.append(num)
    elif isinstance(merge_nums_raw, str) and merge_nums_raw.strip():
        for part in re.split(r"[,+/|]+", merge_nums_raw):
            num = _hotel_str(part.strip(), 20)
            if num and num not in merge_numbers:
                merge_numbers.append(num)
    out["mergeRoomNumbers"] = merge_numbers
    label = _hotel_str(
        stay.get("mergeRoomLabel") or stay.get("merge_room_label"), 120
    )
    if not label and merge_numbers:
        label = " + ".join(merge_numbers)
    out["mergeRoomLabel"] = label
    merge_rates_raw = stay.get("mergeRoomRates") or stay.get("merge_room_rates") or []
    cleaned_rates = []
    if isinstance(merge_rates_raw, list):
        for item in merge_rates_raw[:20]:
            if not isinstance(item, dict):
                continue
            try:
                row_rate = round(float(item.get("roomRate") or item.get("room_rate") or 0), 2)
            except (TypeError, ValueError):
                row_rate = 0.0
            plan = _hotel_str(item.get("ratePlan") or item.get("rate_plan"), 20)
            cleaned_rates.append(
                {
                    "roomId": _hotel_str(item.get("roomId") or item.get("room_id"), 40),
                    "number": _hotel_str(item.get("number") or item.get("roomNumber"), 20),
                    "roomType": _hotel_str(
                        item.get("roomType") or item.get("room_type"), 40
                    ),
                    "roomTypeLabel": _hotel_str(
                        item.get("roomTypeLabel")
                        or item.get("room_type_label")
                        or item.get("roomType")
                        or item.get("label"),
                        80,
                    ),
                    "ratePlan": plan,
                    "roomRate": max(0.0, row_rate),
                    "isPrimary": bool(item.get("isPrimary") or item.get("is_primary")),
                    "nightlyRates": item.get("nightlyRates")
                    if isinstance(item.get("nightlyRates"), list)
                    else (
                        item.get("nightly_rates")
                        if isinstance(item.get("nightly_rates"), list)
                        else []
                    ),
                }
            )
    out["mergeRoomRates"] = cleaned_rates
    # Raw nightlyRates kept until billable nights are known (normalized below).
    out["nightlyRates"] = (
        stay.get("nightlyRates")
        if isinstance(stay.get("nightlyRates"), list)
        else (
            stay.get("nightly_rates")
            if isinstance(stay.get("nightly_rates"), list)
            else []
        )
    )
    history = stay.get("transferHistory") or stay.get("transfer_history") or []
    if isinstance(history, list):
        cleaned = []
        for item in history[-20:]:
            if not isinstance(item, dict):
                continue
            cleaned.append(
                {
                    "fromRoomId": _hotel_str(item.get("fromRoomId") or item.get("from_room_id"), 40),
                    "fromRoomNumber": _hotel_str(
                        item.get("fromRoomNumber") or item.get("from_room_number"), 20
                    ),
                    "toRoomId": _hotel_str(item.get("toRoomId") or item.get("to_room_id"), 40),
                    "toRoomNumber": _hotel_str(
                        item.get("toRoomNumber") or item.get("to_room_number"), 20
                    ),
                    "at": _hotel_str(item.get("at"), 40),
                    "note": _hotel_str(item.get("note"), 200),
                }
            )
        out["transferHistory"] = cleaned
        if cleaned and not out["transferCount"]:
            out["transferCount"] = len(cleaned)
    if out.get("agencyRoomBilling") and out.get("agencyName"):
        if not out.get("invoiceTo"):
            out["invoiceTo"] = out["agencyName"]
        if not out.get("billingName"):
            out["billingName"] = out["agencyName"]
    elif not out.get("agencyRoomBilling"):
        out["invoiceTo"] = ""
        out["billingName"] = ""

    extra_guests = stay.get("additionalGuests") or stay.get("additional_guests") or []
    cleaned_guests = []
    if isinstance(extra_guests, list):
        for item in extra_guests[:12]:
            if not isinstance(item, dict):
                continue
            name = _hotel_str(item.get("name") or item.get("guestName"), 160)
            id_type = _hotel_str(item.get("idType") or item.get("id_type"), 40)
            doc_name = _hotel_str(
                item.get("idDocumentName") or item.get("id_document_name"), 120
            )
            doc_path = _hotel_id_document_view_path(
                doc_name,
                item.get("idDocumentPath") or item.get("id_document_path"),
            )
            doc_mime = _hotel_str(
                item.get("idDocumentMime") or item.get("id_document_mime"), 60
            )
            doc_stored = _hotel_str(
                item.get("idDocumentStoredName")
                or item.get("id_document_stored_name"),
                120,
            )
            if not name and not id_type and not doc_path:
                continue
            cleaned_guests.append(
                {
                    "name": name,
                    "idType": id_type,
                    "idDocumentName": doc_name,
                    "idDocumentPath": doc_path,
                    "idDocumentMime": doc_mime,
                    "idDocumentStoredName": doc_stored,
                }
            )
    out["additionalGuests"] = cleaned_guests
    # Keep adult count at least primary + additional guests.
    out["adults"] = max(out["adults"], 1 + len(cleaned_guests))

    folio_raw = stay.get("folioCharges") or stay.get("folio_charges") or []
    cleaned_folio = []
    if isinstance(folio_raw, list):
        allowed_kinds = {
            "restaurant_room_transfer",
            "bar_room_transfer",
            "other",
        }
        for item in folio_raw[:100]:
            if not isinstance(item, dict):
                continue
            amount = round(_num(item.get("amount"), 0), 2)
            if amount <= 0:
                continue
            kind = _hotel_str(item.get("kind"), 40).lower().replace(" ", "_")
            if kind not in allowed_kinds:
                kind = "other"
            label = _hotel_str(item.get("label"), 120) or kind.replace(
                "_", " "
            ).title()
            order_no = _hotel_str(
                item.get("orderNo") or item.get("order_no"), 40
            )
            if not order_no and "·" in label:
                order_no = label.split("·", 1)[1].strip()[:40]
            line = {
                "id": _hotel_str(item.get("id"), 40),
                "kind": kind,
                "label": label,
                "amount": amount,
                "source": _hotel_str(item.get("source"), 40),
                "invoiceId": _hotel_str(
                    item.get("invoiceId") or item.get("invoice_id"), 40
                ),
                "orderNo": order_no,
                "outlet": _hotel_str(item.get("outlet"), 40),
                "at": _hotel_str(item.get("at"), 40),
                "note": _hotel_str(item.get("note"), 200),
                "sourceRoomId": _hotel_str(
                    item.get("sourceRoomId") or item.get("source_room_id"), 40
                ),
                "sourceRoomNumber": _hotel_str(
                    item.get("sourceRoomNumber") or item.get("source_room_number"), 20
                ),
                "settled": bool(item.get("settled") or item.get("paid")),
                "invoicedInvoiceNumber": _hotel_str(
                    item.get("invoicedInvoiceNumber")
                    or item.get("invoiced_invoice_number"),
                    60,
                ),
            }
            service_date = _hotel_str(
                item.get("serviceDate") or item.get("service_date"), 10
            )
            if service_date and len(service_date) >= 10:
                line["serviceDate"] = service_date[:10]
            qty_raw = item.get("qty")
            if qty_raw is not None and str(qty_raw).strip() != "":
                qty_val = round(_num(qty_raw, 0), 2)
                if qty_val > 0:
                    line["qty"] = qty_val
            rate_raw = item.get("rate")
            if rate_raw is not None and str(rate_raw).strip() != "":
                rate_val = round(_num(rate_raw, 0), 2)
                if rate_val >= 0:
                    line["rate"] = rate_val
            # Preserve POS invoice tax snapshot for F&B room transfers.
            if kind in ("restaurant_room_transfer", "bar_room_transfer"):
                for money_key in (
                    "subtotal",
                    "discount",
                    "gst",
                    "vat",
                    "service",
                    "tip",
                    "grandTotal",
                ):
                    raw = item.get(money_key)
                    if raw is None and money_key == "gst":
                        raw = item.get("gstAmount")
                    if raw is None and money_key == "vat":
                        raw = item.get("vatAmount")
                    if raw is None:
                        continue
                    line[money_key] = round(_num(raw, 0), 2)
                for pct_key in ("taxCgstPct", "taxUgstPct", "vatPct"):
                    raw = item.get(pct_key)
                    if raw is None:
                        continue
                    try:
                        line[pct_key] = float(raw)
                    except (TypeError, ValueError):
                        pass
            cleaned_folio.append(line)
    out["folioCharges"] = cleaned_folio
    # Unmerged rooms bill from roomRate × nights. Leftover absorb lines from a
    # former merge would list every other room and inflate estimatedTotal.
    if out.get("independentBilling") and out.get("mergeRole") not in (
        "member",
        "primary",
    ):
        cleaned_folio = [
            line
            for line in cleaned_folio
            if str(line.get("source") or "").strip()
            not in ("room_merge", "merged_room_rate")
        ]
        out["folioCharges"] = cleaned_folio

    payments_raw = stay.get("payments") or []
    cleaned_payments = []
    payments_total = 0.0
    if isinstance(payments_raw, list):
        for item in payments_raw[:100]:
            if not isinstance(item, dict):
                continue
            amount = round(_num(item.get("amount"), 0), 2)
            if amount <= 0:
                continue
            method = _normalize_hotel_payment_method(
                item.get("method") or item.get("paymentMethod") or item.get("payment_method")
            )
            if not method:
                method = "cash"
            cleaned_payments.append(
                {
                    "id": _hotel_str(item.get("id"), 40)
                    or f"pay-{len(cleaned_payments) + 1}",
                    "amount": amount,
                    "method": method,
                    "reference": _hotel_str(
                        item.get("reference") or item.get("paymentReference"), 80
                    ),
                    "note": _hotel_str(item.get("note"), 200),
                    "at": _hotel_str(item.get("at"), 40),
                }
            )
            payments_total = round(payments_total + amount, 2)
    out["payments"] = cleaned_payments

    # checkInAdvancePaid is the advance captured at check-in (before invoice payments).
    check_in_advance = out["checkInAdvancePaid"]
    if check_in_advance < 0:
        check_in_advance = round(max(0.0, advance - payments_total), 2)
    out["checkInAdvancePaid"] = round(max(0.0, check_in_advance), 2)
    out["advancePaid"] = round(out["checkInAdvancePaid"] + payments_total, 2)

    if out["invoiceNumber"]:
        out["invoiceGenerated"] = True
        if not out.get("invoiceEditOpen"):
            out["invoiceEditOpen"] = False
    elif out["invoiceGenerated"] and not out["invoiceNumber"]:
        out["invoiceGenerated"] = False
        out["invoiceEditOpen"] = False

    if out["billedInvoiceNumber"]:
        out["billedInvoiceGenerated"] = True
    elif out["billedInvoiceGenerated"] and not out["billedInvoiceNumber"]:
        out["billedInvoiceGenerated"] = False
        out["billedInvoiceGeneratedAt"] = ""

    if out["billedFbTransferInvoiceNumber"]:
        out["billedFbTransferInvoiceGenerated"] = True
    elif (
        out["billedFbTransferInvoiceGenerated"]
        and not out["billedFbTransferInvoiceNumber"]
    ):
        out["billedFbTransferInvoiceGenerated"] = False
        out["billedFbTransferInvoiceGeneratedAt"] = ""

    # Fill expected check-out when only nights were provided.
    if not out["checkOutDate"] and out["checkInDate"]:
        in_date = _hotel_parse_iso_date(out["checkInDate"])
        if in_date is not None:
            out["checkOutDate"] = (in_date + timedelta(days=out["nights"])).isoformat()

    overstay_nights = _hotel_overstay_extra_nights(out)
    billable_nights = max(1, out["nights"] + overstay_nights)
    out["overstayNights"] = overstay_nights
    out["billableNights"] = billable_nights

    # Per-night rates: fill missing nights from default / previous night.
    # Legacy flat stays (no nightlyRates) keep empty list → roomRate × nights.
    raw_nightly = out.get("nightlyRates")
    has_nightly_input = isinstance(raw_nightly, list) and bool(raw_nightly)
    if has_nightly_input:
        nightly = _hotel_normalize_nightly_rates(
            raw_nightly,
            check_in=out.get("checkInDate"),
            nights=out["nights"],
            overstay_nights=overstay_nights,
            default_rate=out["roomRate"],
            default_plan=out.get("ratePlan") or "",
        )
        out["nightlyRates"] = nightly
        if nightly:
            out["roomRate"] = nightly[0]["roomRate"]
            out["ratePlan"] = nightly[0]["ratePlan"] or out.get("ratePlan") or ""
    else:
        out["nightlyRates"] = []

    # Normalize nested nightlyRates on each merge room row.
    normalized_merge_rates = []
    for row in out.get("mergeRoomRates") or []:
        if not isinstance(row, dict):
            continue
        row = dict(row)
        row_raw = row.get("nightlyRates")
        row_has_nightly = isinstance(row_raw, list) and bool(row_raw)
        if row_has_nightly:
            row_nightly = _hotel_normalize_nightly_rates(
                row_raw,
                check_in=out.get("checkInDate"),
                nights=out["nights"],
                overstay_nights=overstay_nights,
                default_rate=row.get("roomRate") or out["roomRate"],
                default_plan=row.get("ratePlan") or out.get("ratePlan") or "",
            )
            row["nightlyRates"] = row_nightly
            if row_nightly:
                row["roomRate"] = row_nightly[0]["roomRate"]
                row["ratePlan"] = (
                    row_nightly[0]["ratePlan"] or row.get("ratePlan") or ""
                )
        else:
            row["nightlyRates"] = []
        normalized_merge_rates.append(row)
    out["mergeRoomRates"] = normalized_merge_rates

    # Mirror primary merge row nightlyRates onto stay root when root has none.
    if not out.get("nightlyRates"):
        for row in normalized_merge_rates:
            if isinstance(row, dict) and row.get("isPrimary") and row.get("nightlyRates"):
                out["nightlyRates"] = list(row["nightlyRates"])
                out["roomRate"] = row["roomRate"]
                out["ratePlan"] = row.get("ratePlan") or out.get("ratePlan") or ""
                break

    room_charges = _hotel_stay_room_charges_amount(out, billable_nights)
    out["totalRate"] = room_charges
    hotel_extras = round(
        out["extraBedAmount"]
        + out["earlyCheckinAmount"]
        + out["lateCheckoutAmount"],
        2,
    )
    hotel_folio_total = round(
        sum(item["amount"] for item in cleaned_folio if not _hotel_folio_is_fb_transfer(item)),
        2,
    )
    fb_transfer_total = round(
        sum(item["amount"] for item in cleaned_folio if _hotel_folio_is_fb_transfer(item)),
        2,
    )
    fb_unsettled = round(
        sum(
            item["amount"]
            for item in cleaned_folio
            if _hotel_folio_is_fb_transfer(item) and not item.get("settled")
        ),
        2,
    )
    out["fbTransferTotal"] = fb_transfer_total
    out["fbTransferInvoiceNumber"] = _hotel_str(
        stay.get("fbTransferInvoiceNumber") or stay.get("fb_transfer_invoice_number"),
        60,
    )
    out["fbTransferInvoiceGenerated"] = bool(
        out["fbTransferInvoiceNumber"]
        or stay.get("fbTransferInvoiceGenerated")
        or stay.get("fb_transfer_invoice_generated")
    )
    out["fbTransferInvoiceGeneratedAt"] = _hotel_str(
        stay.get("fbTransferInvoiceGeneratedAt")
        or stay.get("fb_transfer_invoice_generated_at"),
        40,
    )
    fb_payments_raw = stay.get("fbTransferPayments") or stay.get("fb_transfer_payments") or []
    cleaned_fb_payments = []
    if isinstance(fb_payments_raw, list):
        for item in fb_payments_raw[:50]:
            if not isinstance(item, dict):
                continue
            amount = round(_num(item.get("amount"), 0), 2)
            if amount <= 0:
                continue
            cleaned_fb_payments.append(
                {
                    "id": _hotel_str(item.get("id"), 40),
                    "amount": amount,
                    "method": (
                        _normalize_hotel_payment_method(item.get("method"))
                        or (
                            ""
                            if str(item.get("method") or "").strip().lower()
                            in ("checkout", "fb_checkout")
                            else "cash"
                        )
                    ),
                    "reference": _hotel_str(
                        item.get("reference") or item.get("transaction_id"), 80
                    ),
                    "note": _hotel_str(item.get("note"), 200),
                    "invoiceNumber": _hotel_str(
                        item.get("invoiceNumber") or item.get("invoice_number"), 60
                    ),
                    "at": _hotel_str(item.get("at"), 40),
                }
            )
    out["fbTransferPayments"] = cleaned_fb_payments
    out["fbTransferBalance"] = fb_unsettled
    # Merge members are display-only for money — billing lives on primary.
    # Preserve billed* locks so siblings stay "already invoiced" after primary generate.
    if out.get("mergeRole") == "member" or out.get("billingRoomId"):
        out["mergeRole"] = "member"
        billed_no = out.get("billedInvoiceNumber") or ""
        billed_gen = bool(out.get("billedInvoiceGenerated") or billed_no)
        billed_at = out.get("billedInvoiceGeneratedAt") or ""
        billed_fb_no = out.get("billedFbTransferInvoiceNumber") or ""
        billed_fb_gen = bool(out.get("billedFbTransferInvoiceGenerated") or billed_fb_no)
        billed_fb_at = out.get("billedFbTransferInvoiceGeneratedAt") or ""
        out["invoiceNumber"] = ""
        out["invoiceGenerated"] = False
        out["invoiceGeneratedAt"] = ""
        out["billedInvoiceNumber"] = billed_no if billed_gen else ""
        out["billedInvoiceGenerated"] = bool(billed_gen and billed_no)
        out["billedInvoiceGeneratedAt"] = billed_at if out["billedInvoiceGenerated"] else ""
        out["billedFbTransferInvoiceNumber"] = billed_fb_no if billed_fb_gen else ""
        out["billedFbTransferInvoiceGenerated"] = bool(billed_fb_gen and billed_fb_no)
        out["billedFbTransferInvoiceGeneratedAt"] = (
            billed_fb_at if out["billedFbTransferInvoiceGenerated"] else ""
        )
        out["discountType"] = "pct"
        out["discountValue"] = 0.0
        out["discountAmount"] = 0.0
        out["discountReason"] = ""
        estimated = round(hotel_folio_total, 2)
        out["estimatedTotal"] = estimated
        out["balanceAmount"] = 0.0
        out["combinedBalanceDue"] = round(out["balanceAmount"] + out["fbTransferBalance"], 2)
        return out

    discount_type = str(
        stay.get("discountType") or stay.get("discount_type") or "pct"
    ).strip().lower()
    if discount_type not in ("pct", "inr"):
        discount_type = "pct"
    discount_value = round(
        _num(stay.get("discountValue") if "discountValue" in stay else stay.get("discount_value"), 0),
        2,
    )
    if discount_value < 0:
        discount_value = 0.0
    gross = round(room_charges + hotel_extras + hotel_folio_total, 2)
    if discount_type == "inr":
        discount_amount = round(min(gross, discount_value), 2)
    else:
        pct = min(100.0, discount_value)
        discount_value = pct
        discount_amount = round(gross * (pct / 100.0), 2)
    if discount_amount <= 0 or discount_value <= 0:
        discount_type = "pct"
        discount_value = 0.0
        discount_amount = 0.0
        discount_reason = ""
    else:
        discount_reason = _hotel_str(
            stay.get("discountReason") or stay.get("discount_reason"), 200
        )
        effective_pct = (
            discount_value
            if discount_type == "pct"
            else ((discount_amount / gross) * 100.0 if gross > 0 else 0.0)
        )
        if effective_pct <= 15:
            discount_reason = ""
    out["discountType"] = discount_type
    out["discountValue"] = discount_value
    out["discountAmount"] = discount_amount
    out["discountReason"] = discount_reason
    # Room rate / extras / folio on the stay are tax-inclusive.
    inclusive = round(max(gross - discount_amount, 0), 2)
    slab_rates = hotel_tax_rates_for_tariff(
        tax_rates, _hotel_stay_tariff_for_tax_slab(out)
    )
    _taxable, _cgst, _ugst, estimated = _hotel_split_inclusive_tax(
        inclusive, slab_rates
    )
    out["estimatedTotal"] = estimated
    # Prefer computed balance so folio posts stay in sync.
    out["balanceAmount"] = round(max(estimated - out["advancePaid"], 0), 2)
    out["combinedBalanceDue"] = round(out["balanceAmount"] + out["fbTransferBalance"], 2)

    out["hotelInvoicedBillableNights"] = max(
        0, int(_num(stay.get("hotelInvoicedBillableNights"), 0))
    )
    out["hotelInvoicedEstimatedTotal"] = round(
        float(stay.get("hotelInvoicedEstimatedTotal") or 0), 2
    )
    out["hotelInvoicedExtraBedAmount"] = round(
        float(stay.get("hotelInvoicedExtraBedAmount") or 0), 2
    )
    out["hotelInvoicedEarlyCheckinAmount"] = round(
        float(stay.get("hotelInvoicedEarlyCheckinAmount") or 0), 2
    )
    out["hotelInvoicedLateCheckoutAmount"] = round(
        float(stay.get("hotelInvoicedLateCheckoutAmount") or 0), 2
    )
    history_clean = []
    for item in _hotel_invoice_history_raw(stay):
        inv = _hotel_str(item.get("invoiceNumber") or item.get("invoice_number"), 60)
        if not inv:
            continue
        history_clean.append(
            {
                "kind": _hotel_str(item.get("kind"), 10).lower() or "hotel",
                "invoiceNumber": inv,
                "generatedAt": _hotel_str(
                    item.get("generatedAt") or item.get("generated_at"), 40
                ),
                "estimatedTotal": round(float(item.get("estimatedTotal") or 0), 2),
                "balanceAmount": round(float(item.get("balanceAmount") or 0), 2),
                "billableNights": max(
                    0, int(_hotel_num(item.get("billableNights") or item.get("billable_nights"), 0))
                ),
                "folioLineIds": [
                    _hotel_str(x, 40)
                    for x in (item.get("folioLineIds") or item.get("folio_line_ids") or [])
                    if _hotel_str(x, 40)
                ],
                "snapshotStay": item.get("snapshotStay")
                if isinstance(item.get("snapshotStay"), dict)
                else None,
            }
        )
    out["invoiceHistory"] = history_clean[-50:]
    out = _hotel_backfill_invoice_lock_fields(out)
    return out


def _hotel_folio_kind_for_outlet(outlet):
    value = str(outlet or "").strip().lower()
    if value in ("bar", "bars"):
        return "bar_room_transfer"
    if value in ("restaurant", "resto", "dining"):
        return "restaurant_room_transfer"
    return "other"


def update_hotel_room_charge(
    conn,
    room_id,
    *,
    charge_key,
    label="",
    amount=None,
    rate=None,
):
    """Edit a stay charge line (room rate, extras, or folio entry)."""
    room_id = str(room_id or "").strip()
    key = str(charge_key or "").strip()
    if not room_id:
        raise ValueError("Hotel room is required.")
    if not key:
        raise ValueError("Charge key is required.")

    layout = get_hotel_rooms_layout(conn)
    rooms = list(layout.get("rooms") or [])
    target = None
    for room in rooms:
        if str(room.get("id") or "") == room_id or str(room.get("number") or "") == room_id:
            target = room
            break
    if not target:
        raise ValueError("Hotel room not found.")
    stay = target.get("stay")
    if not _hotel_room_stay_editable(target):
        raise ValueError("Select an occupied room with an active stay.")
    stay = _hotel_mutate_stay_charge(
        stay,
        room_id,
        key,
        label=label,
        amount=amount,
        rate=rate,
    )
    target["stay"] = stay
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    refreshed = get_hotel_room(conn, target.get("id") or room_id)
    _hotel_sync_live_invoice_row(conn, refreshed or target)
    return {"room": refreshed or target}


def delete_hotel_room_charge(conn, room_id, *, charge_key):
    """Remove a stay charge line (extras or folio). Room tariff cannot be deleted."""
    room_id = str(room_id or "").strip()
    key = str(charge_key or "").strip()
    if not room_id:
        raise ValueError("Hotel room is required.")
    if not key:
        raise ValueError("Charge key is required.")
    if key == "room" or key.startswith("night:"):
        raise ValueError("Room tariff cannot be deleted.")

    layout = get_hotel_rooms_layout(conn)
    rooms = list(layout.get("rooms") or [])
    target = None
    for room in rooms:
        if str(room.get("id") or "") == room_id or str(room.get("number") or "") == room_id:
            target = room
            break
    if not target:
        raise ValueError("Hotel room not found.")
    stay = target.get("stay")
    if not _hotel_room_stay_editable(target):
        raise ValueError("Select an occupied room with an active stay.")
    stay = _normalize_hotel_room_stay(stay)
    if _hotel_stay_invoice_locked(stay):
        raise ValueError("Charges cannot be deleted after the invoice is generated.")
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to delete charges."
        )

    if key == "extra_bed":
        stay["extraBedAmount"] = 0.0
        stay["extraBedQty"] = 0
        stay["extraBedRate"] = 0.0
        stay["extraBedNights"] = 0
    elif key == "early_checkin":
        stay["earlyCheckinAmount"] = 0.0
        stay["earlyCheckinQty"] = 0
        stay["earlyCheckinRate"] = 0.0
        stay["earlyCheckinNights"] = 0
    elif key == "late_checkout":
        stay["lateCheckoutAmount"] = 0.0
        stay["lateCheckoutQty"] = 0
        stay["lateCheckoutRate"] = 0.0
        stay["lateCheckoutNights"] = 0
    elif key in ("restaurant_room_transfer", "bar_room_transfer"):
        stay["folioCharges"] = [
            item
            for item in (stay.get("folioCharges") or [])
            if str(item.get("kind") or "").lower() != key
        ]
    elif key.startswith("folio:"):
        folio_id = key.split(":", 1)[1].strip()
        before = len(stay.get("folioCharges") or [])
        stay["folioCharges"] = [
            item
            for item in (stay.get("folioCharges") or [])
            if str(item.get("id") or "") != folio_id
        ]
        if len(stay.get("folioCharges") or []) == before:
            raise ValueError("Folio charge not found.")
    else:
        raise ValueError("Unsupported charge line.")

    stay = _normalize_hotel_room_stay(stay)
    target["stay"] = stay
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    refreshed = get_hotel_room(conn, target.get("id") or room_id)
    _hotel_sync_live_invoice_row(conn, refreshed or target)
    return {"room": refreshed or target}


def _pos_invoice_tax_snapshot_for_folio(conn, invoice_id, transfer_amount=None):
    """Tax/totals from a POS bill to store on a hotel folio room-transfer line.

    When ``transfer_amount`` is a partial room-transfer, tax fields are scaled
    proportionally to that share of ``grand_total``.
    """
    try:
        iid = int(invoice_id)
    except (TypeError, ValueError):
        return {}
    if iid <= 0:
        return {}
    ensure_pos_schema(conn)
    row = conn.execute(
        """
        SELECT subtotal, discount_amount, gst_amount, vat_amount, service_amount,
               tip, grand_total, tax_cgst_pct, tax_ugst_pct
        FROM pos_invoices
        WHERE id = ? AND is_active = 1
        """,
        (iid,),
    ).fetchone()
    if not row:
        return {}
    grand = _pos_money(row["grand_total"])
    if grand <= 0.009:
        return {}
    transfer = _pos_money(transfer_amount if transfer_amount is not None else grand)
    if transfer <= 0.009:
        return {}
    ratio = 1.0 if abs(transfer - grand) <= 0.02 else min(1.0, transfer / grand)
    subtotal = _pos_money(_pos_money(row["subtotal"]) * ratio)
    discount = _pos_money(_pos_money(row["discount_amount"]) * ratio)
    gst = _pos_money(_pos_money(row["gst_amount"]) * ratio)
    vat = _pos_money(
        (_pos_money(row["vat_amount"]) if "vat_amount" in row.keys() else 0.0) * ratio
    )
    service = _pos_money(_pos_money(row["service_amount"]) * ratio)
    tip = _pos_money(_pos_money(row["tip"]) * ratio)
    cgst_pct = _row_tax_override_pct(row, "tax_cgst_pct")
    ugst_pct = _row_tax_override_pct(row, "tax_ugst_pct")
    vat_pct = None
    if vat > 0.009 and subtotal > 0.009:
        vat_pct = round((vat / subtotal) * 100.0, 4)
    return {
        "subtotal": subtotal,
        "discount": discount,
        "gst": gst,
        "vat": vat,
        "service": service,
        "tip": tip,
        "grandTotal": _pos_money(transfer),
        "taxCgstPct": cgst_pct,
        "taxUgstPct": ugst_pct,
        "vatPct": vat_pct,
    }


def _hotel_enrich_folio_transfer_tax(conn, stay):
    """Backfill POS tax snapshots onto F&B folio lines that lack them."""
    if not isinstance(stay, dict):
        return stay
    folio = stay.get("folioCharges")
    if not isinstance(folio, list) or not folio:
        return stay
    changed = False
    for item in folio:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in ("restaurant_room_transfer", "bar_room_transfer"):
            continue
        has_tax = (
            float(item.get("gst") or item.get("gstAmount") or 0) > 0.009
            or float(item.get("vat") or item.get("vatAmount") or 0) > 0.009
            or float(item.get("subtotal") or 0) > 0.009
        )
        if has_tax:
            continue
        snap = _pos_invoice_tax_snapshot_for_folio(
            conn,
            item.get("invoiceId") or item.get("invoice_id"),
            transfer_amount=item.get("amount"),
        )
        if not snap:
            continue
        for key, value in snap.items():
            if value is None:
                continue
            item[key] = value
        changed = True
    if changed:
        stay = dict(stay)
        stay["folioCharges"] = folio
    return stay


def append_hotel_room_folio_charge(
    conn,
    room_id,
    *,
    amount,
    kind=None,
    label="",
    source="pos",
    invoice_id="",
    order_no="",
    outlet="",
    note="",
    at=None,
):
    """Append a folio line to an occupied room stay and recompute balance."""
    room_id = str(room_id or "").strip()
    if not room_id:
        raise ValueError("Hotel room is required.")
    amount = round(float(amount or 0), 2)
    if amount <= 0:
        raise ValueError("Folio charge amount must be greater than zero.")

    layout = get_hotel_rooms_layout(conn)
    rooms = list(layout.get("rooms") or [])
    target = None
    for room in rooms:
        if str(room.get("id") or "") == room_id or str(room.get("number") or "") == room_id:
            target = room
            break
    if not target:
        raise ValueError("Hotel room not found.")
    status = str(target.get("status") or "").strip().lower()
    stay = target.get("stay")
    if status != "occupied" or not isinstance(stay, dict) or not stay:
        raise ValueError("Select an occupied room with an active stay.")

    # Merged members bill on the primary room.
    billing_id = str(stay.get("billingRoomId") or "").strip()
    if (stay.get("mergeRole") == "member" or billing_id) and billing_id:
        primary = None
        for room in rooms:
            if str(room.get("id") or "") == billing_id or str(room.get("number") or "") == billing_id:
                primary = room
                break
        if not primary or _normalize_hotel_room_status(primary.get("status")) != "occupied":
            raise ValueError("Shared billing room is not available for folio charges.")
        target = primary
        room_id = str(primary.get("id") or "")
        stay = primary.get("stay")
        if not isinstance(stay, dict) or not stay:
            raise ValueError("Shared billing room has no active stay.")

    folio_kind = kind or _hotel_folio_kind_for_outlet(outlet)
    if folio_kind not in (
        "restaurant_room_transfer",
        "bar_room_transfer",
        "other",
    ):
        folio_kind = "other"
    default_label = {
        "restaurant_room_transfer": "Restaurant Room Transfer",
        "bar_room_transfer": "Bar Room Transfer",
        "other": "Other Charge",
    }.get(folio_kind, "Other Charge")
    stamp = str(at or "").strip()
    if not stamp:
        stamp = conn.execute("SELECT datetime('now','localtime')").fetchone()[0]
    line_id = "fc" + str(abs(hash(f"{room_id}:{invoice_id}:{amount}:{stamp}")))[:8]
    order_no = str(order_no or "").strip()[:40]
    stored_label = str(label or default_label).strip()[:120] or default_label
    if not order_no and "·" in stored_label:
        order_no = stored_label.split("·", 1)[1].strip()[:40]
    line = {
        "id": line_id,
        "kind": folio_kind,
        "label": stored_label,
        "amount": amount,
        "source": str(source or "pos").strip()[:40],
        "invoiceId": str(invoice_id or "").strip()[:40],
        "orderNo": order_no,
        "outlet": str(outlet or "").strip()[:40],
        "at": stamp[:40],
        "note": str(note or "").strip()[:200],
        "settled": False,
    }
    if folio_kind in ("restaurant_room_transfer", "bar_room_transfer") and invoice_id:
        tax_snap = _pos_invoice_tax_snapshot_for_folio(
            conn, invoice_id, transfer_amount=amount
        )
        for key, value in tax_snap.items():
            if value is None:
                continue
            line[key] = value
    folio = list(stay.get("folioCharges") or stay.get("folio_charges") or [])
    folio.append(line)
    stay = dict(stay)
    stay["folioCharges"] = folio
    target["stay"] = _normalize_hotel_room_stay(stay)
    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    room = None
    for item in saved.get("rooms") or []:
        if str(item.get("id") or "") == room_id:
            room = item
            break
    return {"room": room, "charge": line}


def _hotel_mobile_digits(value):
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def _hotel_guest_profile_key(mobile):
    digits = _hotel_mobile_digits(mobile)
    if len(digits) >= 10:
        return digits[-10:]
    return digits if len(digits) >= 8 else ""


_HOTEL_GUEST_PROFILE_KEYS = (
    "title",
    "firstName",
    "lastName",
    "guestName",
    "gender",
    "dateOfBirth",
    "nationality",
    "mobileCountry",
    "mobile",
    "email",
    "address",
    "city",
    "state",
    "country",
    "pin",
    "purposeOfVisit",
    "vipStatus",
    "idType",
    "idNumber",
    "idIssueDate",
    "idExpiryDate",
    "idPlaceOfIssue",
    "idDocumentName",
    "idDocumentPath",
    "idDocumentMime",
    "idDocumentStoredName",
    "additionalGuests",
    "agencyName",
    "agencyGst",
        "agencyAddress",
        "agencyBilling",
        "agencyRoomBilling",
        "agencyFbBilling",
    )

_HOTEL_GUEST_PROFILE_ID_KEYS = (
    "idDocumentName",
    "idDocumentPath",
    "idDocumentMime",
    "idDocumentStoredName",
)


def _hotel_guest_norm_compare_name(guest):
    """Lowercased first+last (or guestName), titles stripped, for returning-guest match."""
    if not isinstance(guest, dict):
        return ""
    first = _hotel_str(guest.get("firstName") or guest.get("first_name"), 80)
    last = _hotel_str(guest.get("lastName") or guest.get("last_name"), 80)
    guest_name = _hotel_str(
        guest.get("guestName") or guest.get("guest_name") or guest.get("name"), 160
    )
    if not first and not last and guest_name:
        _title, first, last = _hotel_split_guest_name(guest_name)
    else:
        _title, split_first, split_rest = _hotel_split_guest_name(
            " ".join(p for p in (first, last) if p)
        )
        first = split_first or first
        last = split_rest or last
    joined = " ".join(p for p in (first, last) if p).strip() or guest_name
    text = re.sub(r"\s+", " ", joined).strip().lower()
    return re.sub(
        r"^(mr|mrs|ms|miss|dr|mx)\.?\s+",
        "",
        text,
        flags=re.IGNORECASE,
    ).strip()


def hotel_guest_names_match(guest, first_name="", last_name="", guest_name=""):
    """True when typed name is empty or matches the saved guest (ignore title/case)."""
    typed = _hotel_guest_norm_compare_name(
        {
            "firstName": first_name,
            "lastName": last_name,
            "guestName": guest_name,
        }
    )
    if not typed:
        return True
    saved = _hotel_guest_norm_compare_name(guest)
    return bool(saved) and saved == typed


def _hotel_profile_id_present(value):
    if isinstance(value, list):
        return any(
            isinstance(item, dict)
            and (
                str(item.get("idDocumentPath") or "").strip()
                or str(item.get("idDocumentName") or "").strip()
            )
            for item in value
        )
    return bool(str(value or "").strip())


def _merge_profile_extra_guests(previous, incoming):
    if incoming is None or not isinstance(incoming, list) or not incoming:
        return previous if isinstance(previous, list) else incoming or []
    prev_by_name = {}
    if isinstance(previous, list):
        for item in previous:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip().lower()
            if name:
                prev_by_name[name] = item
    merged = []
    for item in incoming:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        old = prev_by_name.get(str(row.get("name") or "").strip().lower()) or {}
        for key in _HOTEL_GUEST_PROFILE_ID_KEYS:
            if not _hotel_profile_id_present(row.get(key)) and old.get(key):
                row[key] = old.get(key)
        merged.append(row)
    return merged


def save_hotel_guest_profile(conn, stay):
    """Persist guest contact/ID fields keyed by mobile for returning-guest autofill."""
    if not isinstance(stay, dict):
        return
    ensure_hotel_rooms_schema(conn)
    key = _hotel_guest_profile_key(stay.get("mobile"))
    if not key:
        return
    previous = get_hotel_guest_profile(conn, key) or {}
    profile = dict(previous) if isinstance(previous, dict) else {}
    for field in _HOTEL_GUEST_PROFILE_KEYS:
        if field not in stay:
            continue
        incoming = stay.get(field)
        if field == "additionalGuests":
            profile[field] = _merge_profile_extra_guests(
                previous.get(field), incoming
            )
            continue
        if field in _HOTEL_GUEST_PROFILE_ID_KEYS and not _hotel_profile_id_present(
            incoming
        ) and _hotel_profile_id_present(previous.get(field)):
            continue
        profile[field] = incoming
    profile["mobile"] = key
    profile["returningGuest"] = "Yes"
    blob = json.dumps(profile, ensure_ascii=False)
    conn.execute(
        f"""
        INSERT INTO hotel_guest_profiles (mobile, profile, updated_at)
        VALUES (?, ?, {SQL_NOW})
        ON CONFLICT(mobile) DO UPDATE SET
            profile = excluded.profile,
            updated_at = {SQL_NOW}
        """,
        (key, blob),
    )


def get_hotel_guest_profile(conn, mobile):
    """Load a saved hotel guest profile by mobile digits."""
    ensure_hotel_rooms_schema(conn)
    key = _hotel_guest_profile_key(mobile)
    if not key:
        return None
    row = conn.execute(
        "SELECT profile FROM hotel_guest_profiles WHERE mobile = ?",
        (key,),
    ).fetchone()
    if not row:
        # Also try full digit string if stored that way historically.
        digits = _hotel_mobile_digits(mobile)
        if digits and digits != key:
            row = conn.execute(
                "SELECT profile FROM hotel_guest_profiles WHERE mobile = ?",
                (digits,),
            ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row["profile"] if isinstance(row, dict) else row[0])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    data["returningGuest"] = "Yes"
    return data


def find_hotel_guest_by_mobile(conn, mobile, first_name="", last_name=""):
    """Return guest profile for autofill by mobile number.

    Prefers the saved hotel guest profile (keeps ID files after checkout),
    overlays a live in-house stay when present, then Customer Master.
    """
    digits = _hotel_mobile_digits(mobile)
    if len(digits) < 8:
        return None

    layout = get_hotel_rooms_layout(conn)
    best = None
    best_key = ""
    for room in layout.get("rooms") or []:
        stay = room.get("stay")
        if not isinstance(stay, dict) or not stay:
            continue
        stay_digits = _hotel_mobile_digits(stay.get("mobile"))
        if not stay_digits:
            continue
        # Match full number or last 10 digits (country code variants).
        if stay_digits != digits and not (
            len(digits) >= 10
            and len(stay_digits) >= 10
            and stay_digits[-10:] == digits[-10:]
        ):
            continue
        key = str(
            stay.get("checkedInAt")
            or stay.get("checkInDate")
            or stay.get("bookingDate")
            or ""
        )
        if key >= best_key:
            best_key = key
            best = dict(stay)
            best["_matchedRoomId"] = room.get("id")
            best["_matchedRoomNumber"] = room.get("number")

    saved = get_hotel_guest_profile(conn, mobile)
    guest = None
    if saved:
        guest = dict(saved)
        if best:
            for field, value in best.items():
                if field.startswith("_"):
                    continue
                if field in _HOTEL_GUEST_PROFILE_ID_KEYS or field == "additionalGuests":
                    if not _hotel_profile_id_present(guest.get(field)) and _hotel_profile_id_present(
                        value
                    ):
                        guest[field] = value
                    continue
                if value not in (None, "", [], {}):
                    guest[field] = value
    elif best:
        guest = best

    if guest:
        guest["returningGuest"] = "Yes"
        guest.pop("_matchedRoomId", None)
        guest.pop("_matchedRoomNumber", None)
        guest["nameMatch"] = hotel_guest_names_match(
            guest, first_name, last_name
        )
        return guest

    try:
        ensure_customers_schema(conn)
        mobile10 = digits[-10:] if len(digits) >= 10 else digits
        row = conn.execute(
            """
            SELECT first_name, mobile, email, address
            FROM customers
            WHERE mobile != '' AND (mobile = ? OR mobile LIKE ?)
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
            (mobile10, "%" + mobile10),
        ).fetchone()
    except Exception:
        row = None
    if not row:
        return None
    first = _normalize_customer_first_name(row["first_name"] if row else "")
    guest = {
        "firstName": first,
        "mobile": row["mobile"] or mobile10,
        "mobileCountry": "+91",
        "email": _normalize_customer_email(_customer_row_field(row, "email")),
        "address": _normalize_customer_address(_customer_row_field(row, "address")),
        "returningGuest": "Yes",
    }
    guest["nameMatch"] = hotel_guest_names_match(guest, first_name, last_name)
    return guest


def save_hotel_room_checkin(conn, room_id, stay, status="occupied"):
    """Save guest stay on a room and set status (default occupied)."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    next_status = _normalize_hotel_room_status(status)
    found = False
    normalized_stay = None
    for room in rooms:
        if room.get("id") == target or room.get("number") == target:
            current_status = _normalize_hotel_room_status(room.get("status"))
            if next_status == "occupied" and current_status == "dirty":
                raise ValueError("Room is dirty. Mark it Cleaned before check-in.")
            prev = room.get("stay") if isinstance(room.get("stay"), dict) else {}
            incoming = dict(stay or {})
            # Preserve invoice lock / payments across guest edits unless cleared.
            for key in (
                "invoiceNumber",
                "invoiceGenerated",
                "invoiceGeneratedAt",
                "invoiceEditOpen",
                "payments",
                "checkInAdvancePaid",
                "folioCharges",
            ):
                if key not in incoming and key in prev:
                    incoming[key] = prev.get(key)
            if prev.get("invoiceGenerated") or prev.get("invoiceNumber"):
                # Locked folio: keep money fields from the generated stay.
                for key in (
                    "roomRate",
                    "nights",
                    "totalRate",
                    "extraBedQty",
                    "extraBedRate",
                    "extraBedNights",
                    "extraBedAmount",
                    "extraBedNote",
                    "earlyCheckinQty",
                    "earlyCheckinRate",
                    "earlyCheckinNights",
                    "earlyCheckinAmount",
                    "earlyCheckinNote",
                    "lateCheckoutQty",
                    "lateCheckoutRate",
                    "lateCheckoutNights",
                    "lateCheckoutAmount",
                    "lateCheckoutNote",
                    "checkInAdvancePaid",
                    "advancePaid",
                    "payments",
                    "folioCharges",
                    "invoiceNumber",
                    "invoiceGenerated",
                    "invoiceGeneratedAt",
                ):
                    if key in prev:
                        incoming[key] = prev.get(key)
            elif "checkInAdvancePaid" not in incoming and "check_in_advance_paid" not in incoming:
                # Fresh check-in / edit before invoice: treat form advance as check-in advance.
                incoming["checkInAdvancePaid"] = incoming.get("advancePaid") or incoming.get(
                    "advance_paid"
                ) or 0
                incoming["payments"] = []
            room["stay"] = _normalize_hotel_room_stay(incoming)
            _hotel_validate_agency_billing(room["stay"])
            if not room["stay"].get("bookingNumber"):
                room["stay"]["bookingNumber"] = (
                    f"BK{datetime.now().strftime('%Y%m%d%H%M%S')}"
                )
            if not room["stay"].get("checkedInAt") and next_status == "occupied":
                room["stay"]["checkedInAt"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            room["status"] = next_status
            normalized_stay = room["stay"]
            found = True
            break
    if not found:
        raise ValueError("Room not found.")
    _hotel_sync_merge_group_shared_data(
        rooms,
        tariff_rates=get_hotel_tariff_rates(conn),
        rate_source_room_id=target,
    )
    if normalized_stay:
        # Prefer the post-sync stay on the target room for guest profile save.
        for room in rooms:
            if room.get("id") == target or room.get("number") == target:
                if isinstance(room.get("stay"), dict):
                    normalized_stay = room["stay"]
                break
        try:
            save_hotel_guest_profile(conn, normalized_stay)
        except Exception:
            pass
    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    try:
        ensure_hotel_reservation_merge_groups(conn)
    except ValueError:
        pass
    layout = get_hotel_rooms_layout(conn)
    for room in layout.get("rooms") or []:
        if room.get("id") == target or room.get("number") == target:
            return room
    raise ValueError("Room not found.")


def _hotel_room_payment_payload(payment, *, allow_credit=False):
    """Validate and normalize a payment dict for generate/record actions."""
    raw = payment if isinstance(payment, dict) else {}
    try:
        amount = round(float(raw.get("amount") or 0), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Payment amount is invalid.") from exc
    if amount < 0:
        raise ValueError("Payment amount cannot be negative.")
    method = _normalize_hotel_payment_method(
        raw.get("method") or raw.get("paymentMethod") or raw.get("payment_method")
    )
    if method in ("credit", "bor") and not allow_credit:
        raise ValueError(
            "Credit / Back Office Receipt is only allowed when an agency is on this stay."
        )
    if amount > 0 and not method:
        raise ValueError("Payment method is required.")
    reference = _hotel_str(
        raw.get("reference")
        or raw.get("transaction_id")
        or raw.get("transactionId")
        or raw.get("paymentReference")
        or raw.get("payment_reference"),
        80,
    )
    if method == "bank_transfer" and amount > 0 and not reference:
        raise ValueError("Transaction / reference id is required for bank transfer.")
    receipt_id = None
    if method == "bor" and amount > 0:
        try:
            receipt_id = int(raw.get("receipt_id") or raw.get("receiptId") or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("Select a Back Office Receipt for the BOR payment.") from exc
        if receipt_id <= 0:
            raise ValueError("Select a Back Office Receipt for the BOR payment.")
    note = _hotel_str(raw.get("note") or raw.get("notes"), 200)
    payload = {
        "amount": amount,
        "method": method or "cash",
        "reference": reference,
        "note": note,
    }
    if receipt_id:
        payload["receipt_id"] = receipt_id
    return payload


def _parse_hotel_room_payment_splits(
    raw_splits, max_total, *, require_positive=False, allow_credit=False
):
    """Validate split modes for room invoice payment (sum may be ≤ balance)."""
    try:
        ceiling = round(float(max_total or 0), 2)
    except (TypeError, ValueError):
        ceiling = 0.0
    if ceiling < 0:
        raise ValueError("Balance due cannot be negative.")

    if not isinstance(raw_splits, list) or not raw_splits:
        if require_positive:
            raise ValueError("Add at least one payment mode.")
        return []

    allowed = set(HOTEL_ROOM_PAYMENT_METHODS)
    if not allow_credit:
        allowed.discard("credit")
        allowed.discard("bor")

    parsed = []
    seen = set()
    for raw in raw_splits:
        if not isinstance(raw, dict):
            raise ValueError("Each payment split must be an object.")
        method = _normalize_hotel_payment_method(
            raw.get("payment_method")
            or raw.get("paymentMethod")
            or raw.get("method")
        )
        if method in ("credit", "bor") and not allow_credit:
            raise ValueError(
                "Credit / Back Office Receipt is only allowed when an agency is on this stay."
            )
        if not method or method not in allowed:
            raise ValueError("Select a valid payment mode for each row.")
        if method in seen:
            raise ValueError("Each payment mode can only be used once.")
        seen.add(method)
        try:
            amount = round(float(raw.get("amount") or 0), 2)
        except (TypeError, ValueError) as exc:
            raise ValueError("Enter a valid amount for each payment mode.") from exc
        if amount < 0:
            raise ValueError("Payment amounts cannot be negative.")
        if amount <= 0:
            raise ValueError("Enter a valid amount for each payment mode.")
        reference = _hotel_str(
            raw.get("transaction_id")
            or raw.get("transactionId")
            or raw.get("reference")
            or raw.get("paymentReference"),
            80,
        )
        if method == "bank_transfer" and not reference:
            raise ValueError("Transaction ID is required for bank transfer.")
        if method != "bank_transfer":
            reference = ""
        receipt_id = None
        if method == "bor":
            try:
                receipt_id = int(raw.get("receipt_id") or raw.get("receiptId") or 0)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    "Select a Back Office Receipt for the BOR payment."
                ) from exc
            if receipt_id <= 0:
                raise ValueError("Select a Back Office Receipt for the BOR payment.")
        row = {
            "amount": amount,
            "method": method,
            "reference": reference,
            "note": _hotel_str(raw.get("note") or raw.get("notes"), 200),
        }
        if receipt_id:
            row["receipt_id"] = receipt_id
        parsed.append(row)

    split_total = round(sum(item["amount"] for item in parsed), 2)
    if split_total - ceiling > 0.009:
        raise ValueError(
            f"Modes total ₹{split_total:.2f} exceeds balance due ₹{ceiling:.2f}."
        )
    if require_positive and split_total <= 0:
        raise ValueError("Payment amount must be greater than zero.")
    return parsed


def _append_hotel_room_payment(stay, payment, at=None, *, allow_credit=False):
    """Append a payment onto stay and return the payment record (mutates stay)."""
    payload = _hotel_room_payment_payload(payment, allow_credit=allow_credit)
    amount = payload["amount"]
    if amount <= 0:
        return None
    balance = round(float(stay.get("balanceAmount") or 0), 2)
    if amount - balance > 0.009:
        raise ValueError(
            f"Payment ₹{amount:.2f} exceeds balance due ₹{balance:.2f}."
        )
    stamp = _hotel_str(at, 40) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    payments = list(stay.get("payments") or [])
    record = {
        "id": f"pay-{int(datetime.now().timestamp())}-{len(payments) + 1}",
        "amount": amount,
        "method": payload["method"],
        "reference": payload["reference"],
        "note": payload["note"],
        "at": stamp,
    }
    if payload.get("receipt_id"):
        record["receipt_id"] = int(payload["receipt_id"])
    payments.append(record)
    stay["payments"] = payments
    if not stay.get("paymentMethod"):
        stay["paymentMethod"] = payload["method"]
    if payload["reference"] and not stay.get("paymentReference"):
        stay["paymentReference"] = payload["reference"]
    return record


def _apply_hotel_room_payment_splits(stay, splits, note="", at=None):
    """Append one payment record per split (mutates stay). Returns records."""
    if not splits:
        return []
    stamp = _hotel_str(at, 40) or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    shared_note = _hotel_str(note, 200)
    balance = round(float(stay.get("balanceAmount") or 0), 2)
    total = round(sum(float(s.get("amount") or 0) for s in splits), 2)
    if total - balance > 0.009:
        raise ValueError(
            f"Modes total ₹{total:.2f} exceeds balance due ₹{balance:.2f}."
        )
    records = []
    payments = list(stay.get("payments") or [])
    for split in splits:
        amount = round(float(split.get("amount") or 0), 2)
        if amount <= 0:
            continue
        method = _normalize_hotel_payment_method(split.get("method")) or "cash"
        reference = _hotel_str(split.get("reference"), 80)
        record = {
            "id": f"pay-{int(datetime.now().timestamp())}-{len(payments) + 1}",
            "amount": amount,
            "method": method,
            "reference": reference,
            "note": _hotel_str(split.get("note"), 200) or shared_note,
            "at": stamp,
        }
        if split.get("receipt_id"):
            try:
                record["receipt_id"] = int(split["receipt_id"])
            except (TypeError, ValueError):
                pass
        payments.append(record)
        records.append(record)
        if not stay.get("paymentMethod"):
            stay["paymentMethod"] = method
        if reference and not stay.get("paymentReference"):
            stay["paymentReference"] = reference
    stay["payments"] = payments
    return records


def set_hotel_room_discount(
    conn, room_id, discount_type="pct", discount_value=0, discount_reason=""
):
    """Apply a stay folio discount (pct or fixed ₹) before invoice generation."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    room = None
    for item in rooms:
        if item.get("id") == target or item.get("number") == target:
            room = item
            break
    if not room:
        raise ValueError("Room not found.")
    if _normalize_hotel_room_status(room.get("status")) != "occupied":
        raise ValueError("Only occupied rooms can set a discount.")
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("No guest stay on this room.")
    stay = _normalize_hotel_room_stay(stay)
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to set the discount."
        )
    if _hotel_stay_invoice_locked(stay):
        raise ValueError("Discount cannot be changed after the invoice is generated.")

    dtype = str(discount_type or "pct").strip().lower()
    if dtype not in ("pct", "inr"):
        dtype = "pct"
    try:
        dvalue = round(float(discount_value or 0), 2)
    except (TypeError, ValueError) as exc:
        raise ValueError("Enter a valid discount amount.") from exc
    if dvalue < 0:
        raise ValueError("Discount cannot be negative.")
    reason = _hotel_str(discount_reason, 200)

    # Validate against current gross (before discount) so reason rules match UI.
    room_charges = _hotel_stay_room_charges_amount(stay)
    extras = round(
        float(stay.get("extraBedAmount") or 0)
        + float(stay.get("earlyCheckinAmount") or 0)
        + float(stay.get("lateCheckoutAmount") or 0),
        2,
    )
    folio_total = round(
        sum(
            float(item.get("amount") or 0)
            for item in (stay.get("folioCharges") or [])
            if not _hotel_folio_is_fb_transfer(item)
        ),
        2,
    )
    # Stay already has discount applied in estimatedTotal — rebuild gross from components.
    gross = round(room_charges + extras + folio_total, 2)
    if dtype == "inr":
        amount = round(min(gross, dvalue), 2)
        effective_pct = (amount / gross * 100.0) if gross > 0 else 0.0
    else:
        dvalue = min(100.0, dvalue)
        amount = round(gross * (dvalue / 100.0), 2)
        effective_pct = dvalue
    if amount <= 0 or dvalue <= 0:
        dtype = "pct"
        dvalue = 0.0
        amount = 0.0
        reason = ""
    elif effective_pct > 15 and not reason:
        raise ValueError("Enter a reason for discounts over 15%.")
    elif effective_pct <= 15:
        reason = ""

    stay["discountType"] = dtype
    stay["discountValue"] = dvalue
    stay["discountAmount"] = amount
    stay["discountReason"] = reason
    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    refreshed = get_hotel_room(conn, room.get("id") or target)
    _hotel_sync_live_invoice_row(conn, refreshed or room)
    return {"room": refreshed or room}


def generate_hotel_room_invoice(
    conn, room_id, payment=None, payment_splits=None, note="", invoice_kind=None, created_by=""
):
    """Mint HBE and/or FBE and optionally record payment.

    invoice_kind: None/"all" (both as needed), "hotel" (HBE only), or "fb" (FBE only).
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    room = None
    for item in rooms:
        if item.get("id") == target or item.get("number") == target:
            room = item
            break
    if not room:
        raise ValueError("Room not found.")
    if not _hotel_room_stay_editable(room):
        raise ValueError("Only occupied rooms can generate an invoice.")
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("No guest stay on this room.")

    stay = _normalize_hotel_room_stay(stay)
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to generate the invoice."
        )

    creator = str(created_by or "").strip()
    if creator:
        stay["invoiceCreatedBy"] = creator

    kind = str(invoice_kind or "all").strip().lower()
    if kind in ("room", "hbe", "hotel"):
        kind = "hotel"
    elif kind in ("fb", "fbe", "fnb", "food"):
        kind = "fb"
    else:
        kind = "all"
    want_hotel = kind in ("all", "hotel")
    want_fb = kind in ("all", "fb")

    pending_hotel, pending_hotel_lines = _hotel_pending_hotel_amount(stay)
    pending_fb_lines = _hotel_pending_fb_transfer_lines(stay)
    pending_fb = round(
        sum(float(line.get("amount") or 0) for line in pending_fb_lines), 2
    )
    has_primary_hbe = bool(_hotel_str(stay.get("invoiceNumber"), 60))
    has_any_fbe = bool(
        _hotel_str(stay.get("fbTransferInvoiceNumber"), 60)
        or any(
            _hotel_str(e.get("invoiceNumber"), 60)
            for e in _hotel_invoice_history_raw(stay)
            if _hotel_str(e.get("kind"), 10).lower() == "fb"
        )
    )

    will_mint_hotel = want_hotel and (
        pending_hotel > 0.009
        or (not has_primary_hbe and float(stay.get("estimatedTotal") or 0) > 0.009)
    )
    will_mint_fb = want_fb and (
        pending_fb > 0.009
        or (not has_any_fbe and _hotel_fb_transfer_total(stay) > 0.009)
    )

    if kind == "hotel":
        if not will_mint_hotel:
            if has_primary_hbe:
                raise ValueError("No pending room charges to invoice.")
            raise ValueError("No room charges to invoice yet.")
    elif kind == "fb":
        if not will_mint_fb:
            if has_any_fbe:
                raise ValueError("No pending F&B transfers to invoice.")
            raise ValueError("No F&B room transfers to invoice yet.")
    elif has_primary_hbe or has_any_fbe:
        if pending_hotel <= 0.009 and pending_fb <= 0.009:
            raise ValueError("No pending charges to invoice.")
    else:
        has_hotel_charges = float(stay.get("estimatedTotal") or 0) > 0.009
        has_fb_transfers = _hotel_fb_transfer_total(stay) > 0.009
        if not has_hotel_charges and not has_fb_transfers:
            raise ValueError("No charges to invoice yet.")

    detach_stay_after_save = (
        _normalize_hotel_room_status(room.get("status")) != "occupied"
        and _hotel_stay_edit_unlocked(stay)
    )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    hbe_minted = False
    fb_minted = False
    minted_hbe_no = ""
    minted_fb_no = ""

    if will_mint_hotel:
        invoice_amount = (
            pending_hotel
            if has_primary_hbe
            else round(float(stay.get("estimatedTotal") or 0), 2)
        )
        minted_hbe_no = allocate_hotel_room_invoice_number(conn)
        hbe_minted = True
        if not has_primary_hbe:
            stay["invoiceNumber"] = minted_hbe_no
            stay["invoiceGeneratedAt"] = now
        folio_ids = _hotel_tag_folio_lines(
            stay,
            minted_hbe_no,
            lambda line: not _hotel_folio_is_fb_transfer(line)
            and not _hotel_folio_line_invoiced_no(line),
        )
        snap_stay = _hotel_build_hotel_invoice_snapshot_stay(stay, minted_hbe_no, invoice_amount)

        stay["hotelInvoicedBillableNights"] = max(
            1, int(_hotel_num(stay.get("billableNights"), 1))
        )
        stay["hotelInvoicedEstimatedTotal"] = round(
            float(stay.get("estimatedTotal") or 0), 2
        )
        stay["hotelInvoicedExtraBedAmount"] = round(float(stay.get("extraBedAmount") or 0), 2)
        stay["hotelInvoicedEarlyCheckinAmount"] = round(
            float(stay.get("earlyCheckinAmount") or 0), 2
        )
        stay["hotelInvoicedLateCheckoutAmount"] = round(
            float(stay.get("lateCheckoutAmount") or 0), 2
        )
        _hotel_append_invoice_history(
            stay,
            {
                "kind": "hotel",
                "invoiceNumber": minted_hbe_no,
                "generatedAt": now,
                "estimatedTotal": invoice_amount,
                "balanceAmount": invoice_amount,
                "billableNights": max(1, int(_hotel_num(stay.get("billableNights"), 1))),
                "folioLineIds": folio_ids,
                "snapshotStay": snap_stay,
            },
        )

    if hbe_minted or has_primary_hbe:
        stay["invoiceGenerated"] = True
        stay["invoiceEditOpen"] = False
        if not stay.get("invoiceGeneratedAt"):
            stay["invoiceGeneratedAt"] = now

    linked_pos_orders = []
    if will_mint_fb:
        lines_to_invoice = pending_fb_lines if has_any_fbe else _hotel_fb_transfer_lines(stay)
        minted_fb_no = allocate_fb_transfer_invoice_number(conn)
        fb_minted = True
        if not stay.get("fbTransferInvoiceNumber"):
            stay["fbTransferInvoiceNumber"] = minted_fb_no
            stay["fbTransferInvoiceGeneratedAt"] = now
        folio_ids = [
            _hotel_str(line.get("id"), 40)
            for line in lines_to_invoice
            if _hotel_str(line.get("id"), 40)
        ]
        id_set = set(folio_ids)
        _hotel_tag_folio_lines(
            stay,
            minted_fb_no,
            lambda line: _hotel_str(line.get("id"), 40) in id_set,
        )
        fb_amount = round(sum(float(l.get("amount") or 0) for l in lines_to_invoice), 2)
        snap_fb = _hotel_build_fb_invoice_snapshot_stay(stay, minted_fb_no, lines_to_invoice, now)
        _hotel_append_invoice_history(
            stay,
            {
                "kind": "fb",
                "invoiceNumber": minted_fb_no,
                "generatedAt": now,
                "estimatedTotal": fb_amount,
                "balanceAmount": fb_amount,
                "billableNights": 0,
                "folioLineIds": folio_ids,
                "snapshotStay": snap_fb,
            },
        )
        stay["fbTransferInvoiceGenerated"] = True
        linked_pos_orders = _hotel_fb_transfer_linked_pos_orders(
            {"folioCharges": lines_to_invoice}
        )

    combined_balance = _hotel_combined_checkout_balance(stay)
    allow_credit = _hotel_stay_has_agency(stay)
    payment_records = []
    if payment_splits is not None:
        if _hotel_fb_transfer_unsettled_total(stay) > 0.009:
            payment_records = _apply_combined_stay_payment_splits(
                stay, payment_splits, note=note, allow_credit=allow_credit
            )
        else:
            splits = _parse_hotel_room_payment_splits(
                payment_splits,
                round(float(stay.get("balanceAmount") or 0), 2),
                require_positive=False,
                allow_credit=allow_credit,
            )
            payment_records = _apply_hotel_room_payment_splits(stay, splits, note=note)
    elif payment is not None:
        if _hotel_fb_transfer_unsettled_total(stay) > 0.009:
            payload = _hotel_room_payment_payload(payment, allow_credit=allow_credit)
            if payload and float(payload.get("amount") or 0) > 0.009:
                payment_records = _apply_combined_stay_payment_splits(
                    stay, [payload], note=note, allow_credit=allow_credit
                )
        else:
            record = _append_hotel_room_payment(
                stay, payment, allow_credit=allow_credit
            )
            if record:
                payment_records = [record]

    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    _hotel_snapshot_merge_rooms_on_stay(room, rooms)
    stay = _normalize_hotel_room_stay(room.get("stay") or {})
    room["stay"] = stay
    _hotel_stamp_merge_peers_billed_invoice(rooms, room)
    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    for item in saved.get("rooms") or []:
        if item.get("id") == target or item.get("number") == target:
            _hotel_sync_all_invoice_rows(conn, item)
            if minted_fb_no:
                _retire_pos_room_transfer_invoices_for_stay(
                    conn,
                    item.get("stay") or {},
                    minted_fb_no,
                )
            sync_pos_room_transfer_invoices_for_stay(conn, item)
            inv_no = _hotel_str((item.get("stay") or {}).get("invoiceNumber"), 60)
            if inv_no:
                sync_hotel_invoice_credit_for_number(conn, inv_no)
            fb_no = minted_fb_no or _hotel_str(
                (item.get("stay") or {}).get("fbTransferInvoiceNumber"), 60
            )
            stay_out = item.get("stay") or {}
            if detach_stay_after_save:
                item.pop("stay", None)
                saved = save_hotel_rooms_layout(
                    conn, saved.get("floors") or [], saved.get("rooms") or []
                )
                for refreshed in saved.get("rooms") or []:
                    if refreshed.get("id") == target or refreshed.get("number") == target:
                        item = refreshed
                        break
            return {
                "room": item,
                "minted": hbe_minted,
                "fbMinted": fb_minted,
                "payment": payment_records[0] if payment_records else None,
                "payments": payment_records,
                "hotelInvoice": {
                    "invoiceNumber": minted_hbe_no or inv_no,
                    "balanceAmount": round(float(stay_out.get("balanceAmount") or 0), 2),
                }
                if (minted_hbe_no or inv_no)
                else None,
                "fbInvoice": {
                    "invoiceNumber": fb_no,
                    "balanceAmount": round(float(stay_out.get("fbTransferBalance") or 0), 2),
                    "total": round(
                        float(
                            next(
                                (
                                    e.get("estimatedTotal")
                                    for e in _hotel_invoice_history_entries(stay_out, kind="fb")
                                    if e.get("invoiceNumber") == fb_no
                                ),
                                stay_out.get("fbTransferTotal") or 0,
                            )
                        ),
                        2,
                    ),
                }
                if fb_no
                else None,
                "linkedPosOrders": linked_pos_orders,
                "combinedBalanceDue": round(
                    float(stay_out.get("combinedBalanceDue") or combined_balance), 2
                ),
            }
    raise ValueError("Room not found.")


def require_hotel_room_invoice_for_checkout(conn, room_id):
    """Block checkout of a billing stay until the invoice has been generated.

    Merge members leave a shared bill on the primary and are not blocked here.
    Occupied billing rooms must already have a minted invoice number.
    """
    layout = get_hotel_rooms_layout(conn)
    room = _hotel_find_room(layout.get("rooms") or [], room_id)
    if not room:
        raise ValueError("Room not found.")
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return
    stay = _normalize_hotel_room_stay(stay)
    if _normalize_hotel_room_status(room.get("status")) != "occupied":
        return
    if _hotel_room_is_merge_member(room) or stay.get("mergeRole") == "member" or stay.get(
        "billingRoomId"
    ):
        return
    # Billed via a former merge primary — allow checkout without minting again.
    if stay.get("billedInvoiceGenerated") and stay.get("billedInvoiceNumber"):
        return
    inv_no = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    if not inv_no:
        for entry in _hotel_invoice_history_entries(stay, kind="hotel"):
            inv_no = _hotel_str(entry.get("invoiceNumber"), 60)
            if inv_no:
                stay["invoiceNumber"] = inv_no
                stay["invoiceGenerated"] = True
                break
    if stay.get("invoiceGenerated") and inv_no:
        if _hotel_has_pending_charges(stay):
            raise ValueError(
                "Generate Additional Invoice before check out — pending charges remain."
            )
        if _hotel_fb_transfer_total(stay) > 0.009 and not stay.get(
            "fbTransferInvoiceGenerated"
        ):
            raise ValueError("Generate Invoice to check out (F&B transfers invoice required).")
        return
    raise ValueError("Generate Invoice to check out")


def record_hotel_room_payment(conn, room_id, payment=None, payment_splits=None, note=""):
    """Record a partial/full payment against an already-generated room invoice."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    room = None
    for item in rooms:
        if item.get("id") == target or item.get("number") == target:
            room = item
            break
    if not room:
        raise ValueError("Room not found.")
    if _normalize_hotel_room_status(room.get("status")) != "occupied":
        raise ValueError("Only occupied rooms can record payment.")
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("No guest stay on this room.")
    stay = _normalize_hotel_room_stay(stay)
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        raise ValueError(
            "This room is merged for billing. Open the primary room to record payment."
        )
    if not stay.get("invoiceGenerated") or not stay.get("invoiceNumber"):
        raise ValueError("Generate the invoice before recording payment.")
    combined_balance = _hotel_combined_checkout_balance(stay)
    if combined_balance <= 0.009:
        raise ValueError("Balance due is already settled.")

    allow_credit = _hotel_stay_has_agency(stay)
    agency_name = _hotel_bor_agency_name(stay)
    inv_no = _hotel_str(stay.get("invoiceNumber") or stay.get("invoice_number"), 60)
    payment_records = []
    if payment_splits is not None:
        if _hotel_fb_transfer_unsettled_total(stay) > 0.009:
            splits = _parse_hotel_room_payment_splits(
                payment_splits,
                combined_balance,
                require_positive=True,
                allow_credit=allow_credit,
            )
            _validate_and_consume_hotel_bor_splits(
                conn, splits, agency_name=agency_name, invoice_number=inv_no
            )
            payment_records = _apply_combined_stay_payment_splits(
                stay, splits, note=note, allow_credit=allow_credit
            )
        else:
            splits = _parse_hotel_room_payment_splits(
                payment_splits,
                round(float(stay.get("balanceAmount") or 0), 2),
                require_positive=True,
                allow_credit=allow_credit,
            )
            _validate_and_consume_hotel_bor_splits(
                conn, splits, agency_name=agency_name, invoice_number=inv_no
            )
            payment_records = _apply_hotel_room_payment_splits(stay, splits, note=note)
    else:
        if _hotel_fb_transfer_unsettled_total(stay) > 0.009:
            payload = _hotel_room_payment_payload(payment or {}, allow_credit=allow_credit)
            if not payload or float(payload.get("amount") or 0) <= 0.009:
                raise ValueError("Payment amount must be greater than zero.")
            _validate_and_consume_hotel_bor_splits(
                conn, [payload], agency_name=agency_name, invoice_number=inv_no
            )
            payment_records = _apply_combined_stay_payment_splits(
                stay, [payload], note=note, allow_credit=allow_credit
            )
        else:
            record = _append_hotel_room_payment(
                stay, payment or {}, allow_credit=allow_credit
            )
            if not record:
                raise ValueError("Payment amount must be greater than zero.")
            payment_records = [record]
            _validate_and_consume_hotel_bor_splits(
                conn, [record], agency_name=agency_name, invoice_number=inv_no
            )

    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    for item in saved.get("rooms") or []:
        if item.get("id") == target or item.get("number") == target:
            _hotel_sync_all_invoice_rows(conn, item)
            sync_pos_room_transfer_invoices_for_stay(conn, item)
            inv_no = _hotel_str((item.get("stay") or {}).get("invoiceNumber"), 60)
            if inv_no:
                sync_hotel_invoice_credit_for_number(conn, inv_no)
            return {
                "room": item,
                "payment": payment_records[0] if payment_records else None,
                "payments": payment_records,
            }
    raise ValueError("Room not found.")


def _record_fb_combined_transfer_invoice_payment(
    conn, item, payment=None, payment_splits=None, note=""
):
    """Collect payment against a combined F&B room-transfer invoice (FBE)."""
    inv_no = _hotel_str(item.get("invoice_number"), 60)
    if not inv_no:
        raise ValueError("Invoice not found.")
    balance = round(float(item.get("balance_amount") or 0), 2)
    if balance <= 0.009:
        raise ValueError("Balance due is already settled.")

    room_id = _hotel_str(item.get("room_id"), 40)
    live = get_hotel_room(conn, room_id) if room_id else None
    live_stay = None
    allow_credit = _hotel_invoice_allow_credit(conn, item)
    if live and _normalize_hotel_room_status(live.get("status")) == "occupied":
        live_stay = live.get("stay") if isinstance(live.get("stay"), dict) else None
        if live_stay:
            live_stay = _normalize_hotel_room_stay(live_stay)
            allow_credit = allow_credit or _hotel_stay_has_agency(live_stay)
            if _hotel_str(live_stay.get("fbTransferInvoiceNumber"), 60) != inv_no:
                live_stay = None

    if payment_splits is not None:
        splits = _parse_hotel_room_payment_splits(
            payment_splits,
            balance,
            require_positive=True,
            allow_credit=allow_credit,
        )
        pay_total = round(sum(float(s.get("amount") or 0) for s in splits), 2)
    else:
        payload = _hotel_room_payment_payload(payment or {}, allow_credit=allow_credit)
        if not payload or float(payload.get("amount") or 0) <= 0.009:
            raise ValueError("Payment amount must be greater than zero.")
        splits = [payload]
        pay_total = round(float(payload.get("amount") or 0), 2)

    payment_records = []
    if live_stay:
        payment_records = _apply_fb_transfer_payment_splits(
            live_stay, splits, note=note, invoice_number=inv_no
        )
        applied_total = round(
            sum(float(r.get("amount") or 0) for r in payment_records), 2
        )
        if applied_total <= 0.009:
            raise ValueError("Payment could not be applied to F&B transfers.")
        live_stay = _normalize_hotel_room_stay(live_stay)
        live["stay"] = live_stay
        layout = get_hotel_rooms_layout(conn)
        rooms = layout.get("rooms") or []
        for idx, candidate in enumerate(rooms):
            if str(candidate.get("id") or "") == str(live.get("id") or room_id):
                rooms[idx] = live
                break
        save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
        _hotel_sync_all_invoice_rows(conn, live)
        sync_pos_room_transfer_invoices_for_stay(conn, live)
        refreshed = get_hotel_room_invoice(conn, inv_no)
        return {
            "invoice": refreshed,
            "room": live,
            "payment": payment_records[0] if payment_records else None,
            "payments": payment_records,
        }

    room = dict(item.get("room") or {})
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("Invoice stay data is missing.")
    stay = _normalize_hotel_room_stay(stay)
    payment_records = _apply_fb_transfer_payment_splits(
        stay, splits, note=note, invoice_number=inv_no
    )
    applied_total = round(sum(float(r.get("amount") or 0) for r in payment_records), 2)
    if applied_total <= 0.009:
        raise ValueError("Payment amount must be greater than zero.")
    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    if not room.get("id"):
        room["id"] = room_id
    if not room.get("number"):
        room["number"] = item.get("room_number") or ""
    _hotel_sync_all_invoice_rows(conn, room)
    refreshed = get_hotel_room_invoice(conn, inv_no)
    return {
        "invoice": refreshed,
        "room": (refreshed.get("room") if refreshed else room),
        "payment": payment_records[0] if payment_records else None,
        "payments": payment_records,
    }


def _record_pos_room_transfer_invoice_payment(
    conn, item, payment=None, payment_splits=None, note=""
):
    """Collect a restaurant/bar room-transfer bill from the hotel ledger."""
    inv_no = _hotel_str(item.get("invoice_number"), 60)
    room = dict(item.get("room") or {})
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("Invoice stay data is missing.")
    stay = _normalize_hotel_room_stay(stay)
    stay["invoiceNumber"] = inv_no
    stay["invoiceGenerated"] = True
    balance = round(
        float(item.get("balance_amount") or stay.get("balanceAmount") or 0), 2
    )
    if balance <= 0.009:
        raise ValueError("Balance due is already settled.")
    stay["balanceAmount"] = balance
    stay["estimatedTotal"] = round(
        float(item.get("estimated_total") or balance), 2
    )
    stay["advancePaid"] = round(float(item.get("advance_paid") or 0), 2)
    allow_credit = _hotel_stay_has_agency(stay)
    room_id = _hotel_str(item.get("room_id") or room.get("id"), 40)
    live = get_hotel_room(conn, room_id) if room_id else None
    live_stay = None
    if live and _normalize_hotel_room_status(live.get("status")) == "occupied":
        live_stay = live.get("stay") if isinstance(live.get("stay"), dict) else None
        if live_stay:
            live_stay = _normalize_hotel_room_stay(live_stay)
            allow_credit = allow_credit or _hotel_stay_has_agency(live_stay)
    payment_records = []
    if payment_splits is not None:
        splits = _parse_hotel_room_payment_splits(
            payment_splits,
            balance,
            require_positive=True,
            allow_credit=allow_credit,
        )
        payment_records = _apply_hotel_room_payment_splits(stay, splits, note=note)
    else:
        record = _append_hotel_room_payment(
            stay, payment or {}, allow_credit=allow_credit
        )
        if not record:
            raise ValueError("Payment amount must be greater than zero.")
        payment_records = [record]
    stay = _normalize_hotel_room_stay(stay)
    stay["invoiceNumber"] = inv_no
    stay["invoiceGenerated"] = True
    paid_now = round(sum(float(p.get("amount") or 0) for p in payment_records), 2)
    fully_paid = round(float(stay.get("balanceAmount") or 0), 2) <= 0.009

    if live_stay:
        folio = list(live_stay.get("folioCharges") or [])
        target_line = None
        payload_folio = ""
        payload_order = ""
        try:
            raw = conn.execute(
                "SELECT payload_json FROM hotel_room_invoices WHERE invoice_number = ?",
                (inv_no,),
            ).fetchone()
            blob = json.loads((raw["payload_json"] if raw else "") or "{}")
            if isinstance(blob, dict):
                payload_folio = _hotel_str(blob.get("folioId"), 40)
                payload_order = _hotel_str(
                    blob.get("posOrderNo") or blob.get("pos_order_no"), 60
                )
        except (TypeError, ValueError, json.JSONDecodeError):
            payload_folio = ""
            payload_order = ""
        for line in folio:
            if not line:
                continue
            order_no = _hotel_str(line.get("orderNo") or line.get("order_no"), 60)
            folio_id = _hotel_str(line.get("id"), 40)
            if (
                order_no == inv_no
                or (payload_order and order_no == payload_order)
                or (payload_folio and folio_id == payload_folio)
            ):
                target_line = line
                break
        if target_line and not target_line.get("settled"):
            fb_due = round(float(live_stay.get("fbTransferBalance") or paid_now), 2)
            apply_amount = min(paid_now, fb_due)
            if apply_amount > 0.009:
                _apply_fb_transfer_payment(live_stay, apply_amount, note=note)
            if fully_paid or apply_amount + 0.009 >= float(target_line.get("amount") or 0):
                target_line["settled"] = True
            live_stay["folioCharges"] = folio
            live_stay = _normalize_hotel_room_stay(live_stay)
            live["stay"] = live_stay
            layout = get_hotel_rooms_layout(conn)
            rooms = layout.get("rooms") or []
            for idx, candidate in enumerate(rooms):
                if str(candidate.get("id") or "") == str(live.get("id") or room_id):
                    rooms[idx] = live
                    break
            save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
            if live_stay.get("invoiceNumber"):
                upsert_hotel_room_invoice_from_room(conn, live)
            sync_pos_room_transfer_invoices_for_stay(conn, live)

    room["stay"] = stay
    if not room.get("id"):
        room["id"] = room_id
    if not room.get("number"):
        room["number"] = item.get("room_number") or ""
    payload = {
        "id": room.get("id") or "",
        "number": room.get("number") or "",
        "roomType": room.get("roomType") or "",
        "roomTypeLabel": room.get("roomTypeLabel")
        or item.get("room_type_label")
        or "",
        "floorId": room.get("floorId") or "",
        "status": room.get("status") or "occupied",
        "source": HOTEL_INVOICE_SOURCE_POS_TRANSFER,
        "stay": stay,
    }
    try:
        raw = conn.execute(
            "SELECT payload_json FROM hotel_room_invoices WHERE invoice_number = ?",
            (inv_no,),
        ).fetchone()
        existing_payload = json.loads((raw["payload_json"] if raw else "") or "{}")
        if isinstance(existing_payload, dict):
            for key in ("posInvoiceId", "folioId", "outlet", "stayInvoiceNumber", "posOrderNo"):
                if existing_payload.get(key) and not payload.get(key):
                    payload[key] = existing_payload.get(key)
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    status = _hotel_invoice_status(stay.get("balanceAmount"))
    conn.execute(
        """
        UPDATE hotel_room_invoices
        SET advance_paid = ?,
            balance_amount = ?,
            status = ?,
            payload_json = ?,
            source = ?,
            updated_at = datetime('now','localtime')
        WHERE invoice_number = ?
        """,
        (
            round(float(stay.get("advancePaid") or 0), 2),
            round(float(stay.get("balanceAmount") or 0), 2),
            status,
            json.dumps(payload, separators=(",", ":")),
            HOTEL_INVOICE_SOURCE_POS_TRANSFER,
            inv_no,
        ),
    )
    refreshed = get_hotel_room_invoice(conn, inv_no)
    return {
        "invoice": refreshed,
        "room": (refreshed.get("room") if refreshed else room),
        "payment": payment_records[0] if payment_records else None,
        "payments": payment_records,
    }


def record_hotel_room_invoice_payment(
    conn, invoice_number, payment=None, payment_splits=None, note=""
):
    """Record payment against a ledger invoice (live stay or archive-only)."""
    ensure_hotel_room_invoices_schema(conn)
    item = get_hotel_room_invoice(conn, invoice_number)
    if not item:
        raise ValueError("Invoice not found.")
    inv_no = _hotel_str(item.get("invoice_number"), 60)
    if not inv_no:
        raise ValueError("Invoice not found.")
    if (item.get("status") or "") == "cancelled":
        raise ValueError("Cancelled invoices cannot be settled.")
    if (item.get("status") or "") == "settled" or float(
        item.get("balance_amount") or 0
    ) <= 0.009:
        raise ValueError("Balance due is already settled.")

    payload_source = HOTEL_INVOICE_SOURCE_HOTEL
    try:
        raw = conn.execute(
            "SELECT payload_json FROM hotel_room_invoices WHERE invoice_number = ?",
            (inv_no,),
        ).fetchone()
        blob = json.loads((raw["payload_json"] if raw else "") or "{}")
        if isinstance(blob, dict):
            payload_source = _hotel_invoice_source_value(blob.get("source"))
    except (TypeError, ValueError, json.JSONDecodeError):
        payload_source = HOTEL_INVOICE_SOURCE_HOTEL
    source = _hotel_invoice_source_value(item.get("source") or payload_source)
    if source == HOTEL_INVOICE_SOURCE_POS_TRANSFER:
        result = _record_pos_room_transfer_invoice_payment(
            conn, item, payment=payment, payment_splits=payment_splits, note=note
        )
        refreshed = result.get("invoice") if isinstance(result, dict) else None
        upsert_hotel_invoice_credit(conn, refreshed)
        return result
    if source == HOTEL_INVOICE_SOURCE_FB_COMBINED:
        result = _record_fb_combined_transfer_invoice_payment(
            conn, item, payment=payment, payment_splits=payment_splits, note=note
        )
        refreshed = result.get("invoice") if isinstance(result, dict) else None
        upsert_hotel_invoice_credit(conn, refreshed)
        return result

    room_id = _hotel_str(item.get("room_id"), 40)
    live = get_hotel_room(conn, room_id) if room_id else None
    if live and _normalize_hotel_room_status(live.get("status")) == "occupied":
        live_stay = live.get("stay") if isinstance(live.get("stay"), dict) else None
        if live_stay:
            live_stay = _normalize_hotel_room_stay(live_stay)
            live_inv = _hotel_str(
                live_stay.get("invoiceNumber") or live_stay.get("invoice_number"), 60
            )
            if live_inv == inv_no:
                result = record_hotel_room_payment(
                    conn,
                    room_id,
                    payment=payment,
                    payment_splits=payment_splits,
                    note=note,
                )
                refreshed = get_hotel_room_invoice(conn, inv_no)
                return {
                    "invoice": refreshed,
                    "room": result.get("room")
                    or (refreshed.get("room") if refreshed else None),
                    "payment": result.get("payment"),
                    "payments": result.get("payments") or [],
                }

    room = dict(item.get("room") or {})
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        raise ValueError("Invoice stay data is missing.")
    stay = _normalize_hotel_room_stay(stay)
    if float(stay.get("balanceAmount") or 0) <= 0.009:
        raise ValueError("Balance due is already settled.")
    if not stay.get("invoiceGenerated") or not (
        stay.get("invoiceNumber") or stay.get("invoice_number")
    ):
        stay["invoiceGenerated"] = True
        stay["invoiceNumber"] = inv_no

    balance = round(float(stay.get("balanceAmount") or 0), 2)
    allow_credit = _hotel_stay_has_agency(stay)
    agency_name = _hotel_bor_agency_name(stay)
    payment_records = []
    if payment_splits is not None:
        splits = _parse_hotel_room_payment_splits(
            payment_splits,
            balance,
            require_positive=True,
            allow_credit=allow_credit,
        )
        _validate_and_consume_hotel_bor_splits(
            conn, splits, agency_name=agency_name, invoice_number=inv_no
        )
        payment_records = _apply_hotel_room_payment_splits(stay, splits, note=note)
    else:
        record = _append_hotel_room_payment(
            stay, payment or {}, allow_credit=allow_credit
        )
        if not record:
            raise ValueError("Payment amount must be greater than zero.")
        payment_records = [record]
        _validate_and_consume_hotel_bor_splits(
            conn,
            [record],
            agency_name=agency_name,
            invoice_number=inv_no,
        )

    stay = _normalize_hotel_room_stay(stay)
    room["stay"] = stay
    if not room.get("id"):
        room["id"] = room_id
    if not room.get("number"):
        room["number"] = item.get("room_number") or ""
    upsert_hotel_room_invoice_from_room(conn, room)
    sync_pos_room_transfer_invoices_for_stay(conn, room)
    refreshed = get_hotel_room_invoice(conn, inv_no)
    upsert_hotel_invoice_credit(conn, refreshed)
    return {
        "invoice": refreshed,
        "room": (refreshed.get("room") if refreshed else room),
        "payment": payment_records[0] if payment_records else None,
        "payments": payment_records,
    }


def _allocate_hotel_invoice_payment_splits(items, splits):
    """Assign payment splits across invoices in list order until the pool is empty."""
    pool = [dict(split) for split in splits or []]
    allocations = []
    for item in items or []:
        need = round(float(item.get("balance_amount") or 0), 2)
        taken = []
        while need > 0.009 and pool:
            head = pool[0]
            avail = round(float(head.get("amount") or 0), 2)
            if avail <= 0.009:
                pool.pop(0)
                continue
            take = round(min(avail, need), 2)
            piece = dict(head)
            piece["amount"] = take
            taken.append(piece)
            leftover = round(avail - take, 2)
            need = round(need - take, 2)
            if leftover <= 0.009:
                pool.pop(0)
            else:
                remaining = dict(head)
                remaining["amount"] = leftover
                pool[0] = remaining
        if taken:
            allocations.append((item, taken))
    leftover_total = round(sum(float(split.get("amount") or 0) for split in pool), 2)
    return allocations, leftover_total


def record_hotel_room_invoices_payment(
    conn, invoice_numbers, payment=None, payment_splits=None, note=""
):
    """Record one payment across multiple open ledger invoices (FIFO)."""
    ensure_hotel_room_invoices_schema(conn)
    nums = []
    seen = set()
    raw_list = invoice_numbers if isinstance(invoice_numbers, (list, tuple)) else []
    for raw in raw_list:
        inv_no = _hotel_str(raw, 60)
        if not inv_no:
            continue
        if inv_no in seen:
            raise ValueError("The same invoice was selected more than once.")
        seen.add(inv_no)
        nums.append(inv_no)
    if not nums:
        raise ValueError("Select at least one invoice.")

    items = []
    combined = 0.0
    allow_credit_all = True
    for inv_no in nums:
        item = get_hotel_room_invoice(conn, inv_no)
        if not item:
            raise ValueError(f"Invoice not found: {inv_no}")
        if (item.get("status") or "") == "cancelled":
            raise ValueError(f"Invoice {inv_no} is cancelled.")
        if (item.get("status") or "") == "settled" or float(
            item.get("balance_amount") or 0
        ) <= 0.009:
            raise ValueError(f"Invoice {inv_no} is already settled.")
        items.append(item)
        combined = round(combined + float(item.get("balance_amount") or 0), 2)
        if not _hotel_invoice_allow_credit(conn, item):
            allow_credit_all = False

    if payment_splits is not None:
        splits = _parse_hotel_room_payment_splits(
            payment_splits,
            combined,
            require_positive=True,
            allow_credit=allow_credit_all,
        )
    else:
        payload = _hotel_room_payment_payload(
            payment or {}, allow_credit=allow_credit_all
        )
        if not payload or float(payload.get("amount") or 0) <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        splits = [payload]

    allocations, leftover = _allocate_hotel_invoice_payment_splits(items, splits)
    if leftover > 0.009:
        raise ValueError(
            f"Modes total exceeds combined balance due ₹{combined:.2f}."
        )
    if not allocations:
        raise ValueError("Enter a payment amount.")

    results = []
    for item, taken in allocations:
        results.append(
            record_hotel_room_invoice_payment(
                conn,
                item.get("invoice_number"),
                payment_splits=taken,
                note=note,
            )
        )
    invoices = [row.get("invoice") for row in results if row]
    return {
        "invoices": invoices,
        "invoice": invoices[0] if len(invoices) == 1 else None,
        "payments": [row.get("payment") for row in results],
        "settled_count": sum(
            1
            for inv in invoices
            if inv and (inv.get("status") or "") == "settled"
        ),
        "paid_count": len(invoices),
    }


def _hotel_stay_date_window(stay):
    """Return (check_in, check_out) ISO dates for a stay, or (None, None)."""
    if not isinstance(stay, dict):
        return None, None
    check_in = str(
        stay.get("checkInDate") or stay.get("check_in_date") or ""
    ).strip()[:10]
    check_out = str(
        stay.get("checkOutDate") or stay.get("check_out_date") or ""
    ).strip()[:10]
    if not check_in:
        return None, None
    if not check_out:
        try:
            check_out = (
                datetime.strptime(check_in, "%Y-%m-%d") + timedelta(days=1)
            ).strftime("%Y-%m-%d")
        except ValueError:
            return check_in, None
    return check_in, check_out


def _hotel_date_ranges_overlap(a_in, a_out, b_in, b_out):
    """Inclusive checkout-day overlap (matches front-desk stay coverage)."""
    if not (a_in and a_out and b_in and b_out):
        return False
    return a_in <= b_out and b_in <= a_out


def hotel_room_available_for_stay(
    room, check_in, check_out, *, today=None
) -> bool:
    """True when the room can take a reservation for [check_in, check_out].

    Occupied/reserved rooms are still available when the new window does not
    overlap the current or upcoming stay (queued as upcomingStay on assign).
    """
    if not isinstance(room, dict):
        return False
    status = _normalize_hotel_room_status(room.get("status"))
    cin = str(check_in or "").strip()[:10]
    cout = str(check_out or "").strip()[:10]
    if not cin or not cout or cout <= cin:
        return False
    if status == "out_of_order":
        return False
    if today is None:
        today_iso = date.today().isoformat()
    elif hasattr(today, "isoformat"):
        today_iso = today.isoformat()
    else:
        today_iso = str(today).strip()[:10]
    if status == "dirty" and cin <= today_iso:
        return False
    stay_in, stay_out = _hotel_stay_date_window(
        room.get("stay") if isinstance(room.get("stay"), dict) else None
    )
    if stay_in and stay_out and _hotel_date_ranges_overlap(cin, cout, stay_in, stay_out):
        return False
    upcoming = room.get("upcomingStay")
    if not isinstance(upcoming, dict):
        upcoming = room.get("upcoming_stay")
    up_in, up_out = _hotel_stay_date_window(
        upcoming if isinstance(upcoming, dict) else None
    )
    if up_in and up_out and _hotel_date_ranges_overlap(cin, cout, up_in, up_out):
        return False
    return True


def save_hotel_room_reservation(
    conn, room_id, check_in_date, check_out_date=None, stay_fields=None, replace=False
):
    """Reserve a room for a date window; merges into existing stay when present.

    When replace=True, discard the previous stay and build a fresh reservation.
    When the room is occupied and the new window does not overlap the in-house
    stay, store the booking as upcomingStay without clearing the current guest.
    """
    room = get_hotel_room(conn, room_id)
    if not room:
        raise ValueError("Room not found.")
    status = _normalize_hotel_room_status(room.get("status"))
    stay_existing = room.get("stay") if isinstance(room.get("stay"), dict) else None
    upcoming_existing = (
        room.get("upcomingStay")
        if isinstance(room.get("upcomingStay"), dict)
        else (
            room.get("upcoming_stay")
            if isinstance(room.get("upcoming_stay"), dict)
            else None
        )
    )

    check_in = str(check_in_date or "").strip()[:10]
    if not check_in:
        raise ValueError("From date is required.")
    check_out = str(check_out_date or "").strip()[:10]
    if not check_out:
        try:
            base = datetime.strptime(check_in, "%Y-%m-%d")
            check_out = (base + timedelta(days=1)).strftime("%Y-%m-%d")
        except ValueError as exc:
            raise ValueError("From date is invalid.") from exc
    else:
        check_out = check_out[:10]
    if check_out <= check_in:
        raise ValueError("To date must be after from date.")

    existing_in, existing_out = _hotel_stay_date_window(stay_existing)
    upcoming_in, upcoming_out = _hotel_stay_date_window(upcoming_existing)

    stay_overlaps = bool(
        existing_in
        and existing_out
        and _hotel_date_ranges_overlap(check_in, check_out, existing_in, existing_out)
    )

    # Occupied stay window — reject overlapping dates (keep in-house guest).
    if status == "occupied" and stay_existing and stay_overlaps:
        raise ValueError(
            "Room is occupied for these dates. Choose dates after the "
            "current guest's checkout."
        )

    # Reserved stay window — reject overlapping dates instead of merging guests.
    if status == "reserved" and stay_existing and stay_overlaps:
        raise ValueError(
            "These dates are already reserved. Use Edit Reservation to update "
            "this booking, or choose dates after the current stay."
        )

    if upcoming_in and upcoming_out and _hotel_date_ranges_overlap(
        check_in, check_out, upcoming_in, upcoming_out
    ):
        raise ValueError(
            "These dates already have an upcoming reservation on this room."
        )

    fields = stay_fields if isinstance(stay_fields, dict) else {}
    merge_keys = (
        "guestName",
        "firstName",
        "lastName",
        "mobile",
        "mobileCountry",
        "email",
        "agencyName",
        "agencyGst",
        "agencyAddress",
        "agencyBilling",
        "agencyRoomBilling",
        "agencyFbBilling",
        "invoiceTo",
        "billingName",
        "roomRate",
        "ratePlan",
        "totalRate",
        "advancePaid",
        "additionalRequests",
        "reservationId",
        "reservationBookingId",
    )

    def _build_reservation_stay(base_stay, *, fresh):
        stay = {} if fresh else dict(base_stay or {})
        for key in merge_keys:
            if key in fields:
                stay[key] = fields[key]
            elif fresh or replace:
                if key in ("agencyBilling", "agencyRoomBilling", "agencyFbBilling"):
                    stay[key] = False
                elif key in ("roomRate", "totalRate", "advancePaid"):
                    stay[key] = 0
                elif key == "ratePlan":
                    stay[key] = ""
                else:
                    stay[key] = ""

        guest_name = _hotel_str(stay.get("guestName") or stay.get("guest_name"), 160)
        first = _hotel_str(stay.get("firstName") or stay.get("first_name"), 80)
        last = _hotel_str(stay.get("lastName") or stay.get("last_name"), 80)
        title = _hotel_str(stay.get("title"), 20)
        first_as_title = _hotel_normalize_title_token(first)
        if first_as_title:
            title = title or first_as_title
            first = ""
        if guest_name and not (first or last):
            title_from_name, first, last = _hotel_split_guest_name(guest_name)
            if title_from_name and not title:
                title = title_from_name
        elif first_as_title and last:
            _t2, f2, l2 = _hotel_split_guest_name(last)
            first = f2 or last
            last = l2 or first
        stay["firstName"] = first
        stay["lastName"] = last
        if title:
            stay["title"] = title
        if not guest_name and (first or last):
            guest_name = " ".join(p for p in (first, last) if p).strip()
            stay["guestName"] = guest_name

        stay["checkInDate"] = check_in
        stay["checkOutDate"] = check_out
        try:
            start = datetime.strptime(check_in, "%Y-%m-%d")
            end = datetime.strptime(check_out, "%Y-%m-%d")
            stay["nights"] = max(1, (end - start).days)
        except ValueError:
            stay["nights"] = max(1, int(stay.get("nights") or 1))

        room_bill, fb_bill = _hotel_stay_agency_bill_flags(stay)
        stay["agencyRoomBilling"] = room_bill
        stay["agencyFbBilling"] = fb_bill
        stay["agencyBilling"] = bool(room_bill or fb_bill)
        if room_bill and stay.get("agencyName"):
            stay["invoiceTo"] = stay.get("invoiceTo") or stay.get("agencyName")
            stay["billingName"] = stay.get("billingName") or stay.get("agencyName")
        elif fresh or replace:
            stay["invoiceTo"] = stay.get("invoiceTo") or ""
            stay["billingName"] = stay.get("billingName") or ""

        if not str(stay.get("additionalRequests") or "").strip():
            alias_notes = (
                fields.get("specialNotes")
                or fields.get("special_notes")
                or fields.get("notes")
                or stay.get("specialNotes")
                or stay.get("special_notes")
                or stay.get("notes")
                or ""
            )
            if str(alias_notes).strip():
                stay["additionalRequests"] = str(alias_notes).strip()

        # Seed nightly rate from hotel tariff when reservation has no price yet.
        try:
            rate_val = float(stay.get("roomRate") or stay.get("room_rate") or 0)
        except (TypeError, ValueError):
            rate_val = 0.0
        if rate_val <= 0:
            stay["roomRate"] = _hotel_rate_for_room_type(
                room.get("roomType") or room.get("room_type"),
                get_hotel_tariff_rates(conn),
            )

        if fresh or replace:
            stay["invoiceNumber"] = ""
            stay["invoiceGenerated"] = False
            stay["invoiceGeneratedAt"] = ""
            stay["payments"] = []
            stay["folioCharges"] = []
            stay["checkInAdvancePaid"] = 0
            if "advancePaid" not in fields:
                stay["advancePaid"] = 0
            stay["discountType"] = "pct"
            stay["discountValue"] = 0
            stay["discountAmount"] = 0
            stay["discountReason"] = ""
        return stay

    # Occupied, or reserved without replace, with a non-overlapping future
    # window → queue as upcomingStay without clearing the current guest.
    if stay_existing and (
        status == "occupied" or (status == "reserved" and not replace)
    ):
        upcoming = _normalize_hotel_room_stay(_build_reservation_stay({}, fresh=True))
        if not upcoming.get("bookingNumber"):
            upcoming["bookingNumber"] = f"BK{datetime.now().strftime('%Y%m%d%H%M%S')}"
        layout = get_hotel_rooms_layout(conn)
        rooms = layout.get("rooms") or []
        target = str(room_id or "").strip()
        found = False
        for row in rooms:
            if not isinstance(row, dict):
                continue
            if str(row.get("id") or "") == target or str(row.get("number") or "") == target:
                row["upcomingStay"] = upcoming
                row.pop("upcoming_stay", None)
                found = True
                break
        if not found:
            raise ValueError("Room not found.")
        saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
        for row in saved.get("rooms") or []:
            if str(row.get("id") or "") == target or str(row.get("number") or "") == target:
                result = dict(row)
                enrich_hotel_room_merge_fields(result, saved.get("rooms"))
                return result
        raise ValueError("Room not found.")

    stay = _build_reservation_stay(stay_existing, fresh=bool(replace))
    # Clear any queued upcoming when taking the primary reserved slot.
    result = save_hotel_room_checkin(conn, room_id, stay, status="reserved")
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    changed = False
    for row in rooms:
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") == target or str(row.get("number") or "") == target:
            if "upcomingStay" in row or "upcoming_stay" in row:
                row.pop("upcomingStay", None)
                row.pop("upcoming_stay", None)
                changed = True
            break
    if changed:
        saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
        for row in saved.get("rooms") or []:
            if str(row.get("id") or "") == target or str(row.get("number") or "") == target:
                return row
    return result


def _new_hotel_merge_group_id():
    return f"hmg_{datetime.now().strftime('%Y%m%d%H%M%S')}_{os.getpid() % 10000:04d}"


def _hotel_find_room(rooms, room_id):
    target = str(room_id or "").strip()
    if not target:
        return None
    for room in rooms or []:
        if not isinstance(room, dict):
            continue
        if room.get("id") == target or room.get("number") == target:
            return room
    return None


_HOTEL_LOCAL_BOOKING_RE = re.compile(r"^BK\d{8,}$", re.I)


def _hotel_normalize_reservation_id(value):
    """Provider/reservation id; local BK… booking numbers are not a merge key."""
    text = str(value or "").strip()
    if not text or _HOTEL_LOCAL_BOOKING_RE.match(text):
        return ""
    return text


def _hotel_stay_reservation_ids(stay):
    if not isinstance(stay, dict):
        return []
    found = []
    seen = set()
    for key in (
        "reservationId",
        "reservation_id",
        "providerReservationId",
        "provider_reservation_id",
        "reservationBookingId",
        "reservation_booking_id",
        "bookingId",
        "booking_id",
    ):
        rid = _hotel_normalize_reservation_id(stay.get(key))
        if rid and rid not in seen:
            seen.add(rid)
            found.append(rid)
    return found


def _hotel_stay_reservation_id(stay):
    ids = _hotel_stay_reservation_ids(stay)
    return ids[0] if ids else ""


def _hotel_stay_matches_reservation(stay, reservation_id):
    rid = _hotel_normalize_reservation_id(reservation_id)
    if not rid:
        return False
    return rid in _hotel_stay_reservation_ids(stay)


def _hotel_room_is_merge_member(room):
    if not isinstance(room, dict):
        return False
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    if stay.get("mergeRole") == "member" or stay.get("billingRoomId"):
        return True
    return bool(room.get("mergePrimary") is False and _hotel_room_merge_group_id(room))


def _hotel_rooms_sharing_reservation(rooms, reservation_id):
    """Occupied/reserved rooms whose stay carries this reservation id."""
    rid = _hotel_normalize_reservation_id(reservation_id)
    if not rid:
        return []
    out = []
    for room in rooms or []:
        if not isinstance(room, dict):
            continue
        status = _normalize_hotel_room_status(room.get("status"))
        if status not in ("occupied", "reserved"):
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        if stay and _hotel_stay_independent_billing(stay):
            continue
        if stay and _hotel_stay_matches_reservation(stay, rid):
            out.append(room)
    return out


def _hotel_billing_primary_for_room(rooms, room):
    if not isinstance(room, dict):
        return None
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    billing_id = str(stay.get("billingRoomId") or "").strip()
    if billing_id:
        found = _hotel_find_room(rooms, billing_id)
        if found:
            return found
    gid = _hotel_room_merge_group_id(room)
    if gid:
        for peer in _hotel_rooms_in_merge_group(rooms, gid):
            if peer.get("mergePrimary") and not _hotel_room_is_merge_member(peer):
                return peer
        for peer in _hotel_rooms_in_merge_group(rooms, gid):
            pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else {}
            if pstay.get("mergeRole") == "primary":
                return peer
    return room


def _hotel_pick_reservation_merge_primary(rooms, peers):
    if not peers:
        return None
    peer_ids = {str(p.get("id") or "") for p in peers}

    def _prefer(candidates):
        if not candidates:
            return None
        for room in candidates:
            if room.get("mergePrimary") and not _hotel_room_is_merge_member(room):
                return room
        for room in candidates:
            billed = _hotel_billing_primary_for_room(rooms, room)
            if (
                billed
                and str(billed.get("id") or "") in peer_ids
                and not _hotel_room_is_merge_member(billed)
            ):
                return billed
        for room in candidates:
            if not _hotel_room_is_merge_member(room):
                return room
        return candidates[0]

    occupied = [
        p
        for p in peers
        if _normalize_hotel_room_status(p.get("status")) == "occupied"
    ]
    reserved = [
        p
        for p in peers
        if _normalize_hotel_room_status(p.get("status")) == "reserved"
    ]
    return _prefer(occupied) or _prefer(reserved) or peers[0]


def _hotel_room_merge_group_id(room):
    if not isinstance(room, dict):
        return ""
    return str(room.get("mergeGroupId") or "").strip()


def _hotel_rooms_in_merge_group(rooms, group_id):
    gid = str(group_id or "").strip()
    if not gid:
        return []
    return [
        r
        for r in (rooms or [])
        if isinstance(r, dict) and str(r.get("mergeGroupId") or "").strip() == gid
    ]


def _hotel_stamp_merge_peers_billed_invoice(rooms, primary_room):
    """Mark merge members as billed via the primary's shared invoice (no separate HBE).

    Ledger rows stay on the primary only. Members keep a durable billed* lock so
    Generate is hidden even when live invoiceNumber is cleared on members.
    """
    if not isinstance(primary_room, dict):
        return
    group_id = _hotel_room_merge_group_id(primary_room)
    if not group_id:
        return
    pstay = primary_room.get("stay") if isinstance(primary_room.get("stay"), dict) else {}
    inv_no = _hotel_str(pstay.get("invoiceNumber"), 60)
    inv_at = _hotel_str(pstay.get("invoiceGeneratedAt"), 40)
    inv_gen = bool(pstay.get("invoiceGenerated") and inv_no)
    fb_no = _hotel_str(pstay.get("fbTransferInvoiceNumber"), 60)
    fb_at = _hotel_str(pstay.get("fbTransferInvoiceGeneratedAt"), 40)
    fb_gen = bool(
        (pstay.get("fbTransferInvoiceGenerated") or False) and fb_no
    ) or bool(fb_no)
    if not inv_gen and not fb_gen:
        return
    primary_id = str(primary_room.get("id") or "")
    for peer in _hotel_rooms_in_merge_group(rooms, group_id):
        if not isinstance(peer, dict):
            continue
        if str(peer.get("id") or "") == primary_id:
            continue
        mstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
        if not mstay:
            continue
        mstay = dict(mstay)
        if inv_gen:
            mstay["billedInvoiceNumber"] = inv_no
            mstay["billedInvoiceGenerated"] = True
            mstay["billedInvoiceGeneratedAt"] = inv_at or datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        if fb_gen:
            mstay["billedFbTransferInvoiceNumber"] = fb_no
            mstay["billedFbTransferInvoiceGenerated"] = True
            mstay["billedFbTransferInvoiceGeneratedAt"] = fb_at or datetime.now().strftime(
                "%Y-%m-%d %H:%M:%S"
            )
        peer["stay"] = _normalize_hotel_room_stay(mstay)


def _hotel_clear_room_merge_fields(room):
    if not isinstance(room, dict):
        return
    room.pop("mergeGroupId", None)
    room.pop("mergePrimary", None)


def _hotel_member_stay_from_occupied(stay, billing_room_id):
    """Keep guest display fields; strip billing to the primary room."""
    member = dict(stay) if isinstance(stay, dict) else {}
    member["billingRoomId"] = str(billing_room_id or "").strip()
    member["mergeRole"] = "member"
    member["folioCharges"] = []
    member["payments"] = []
    member["advancePaid"] = 0
    member["checkInAdvancePaid"] = 0
    member["invoiceNumber"] = ""
    member["invoiceGenerated"] = False
    member["invoiceGeneratedAt"] = ""
    member["billedInvoiceNumber"] = ""
    member["billedInvoiceGenerated"] = False
    member["billedInvoiceGeneratedAt"] = ""
    member["billedFbTransferInvoiceNumber"] = ""
    member["billedFbTransferInvoiceGenerated"] = False
    member["billedFbTransferInvoiceGeneratedAt"] = ""
    member["independentBilling"] = False
    # Room rate kept for display on board; normalize zeros money via mergeRole.
    return _normalize_hotel_room_stay(member)


def _hotel_stay_room_rate_only_amount(stay):
    """Primary room tariff for the stay (sum of nightlyRates, or rate × nights)."""
    stay = stay if isinstance(stay, dict) else {}
    try:
        nights = max(1, int(float(stay.get("nights") or 1)))
    except (TypeError, ValueError):
        nights = 1
    overstay = _hotel_overstay_extra_nights(stay)
    billable = max(1, nights + overstay)
    return _hotel_stay_room_charges_amount(stay, billable)


def _hotel_rate_for_room_type(room_type, tariff_rates=None):
    """Nightly tariff for a room type key from settings (or built-in defaults)."""
    key = str(room_type or "").strip()
    rates = tariff_rates if isinstance(tariff_rates, dict) else None
    defaults = HOTEL_DEFAULT_TARIFF_RATES
    if key not in (
        "premium_without_balcony",
        "premium_deluxe_balcony",
        "premium_suite_tub",
    ):
        return 0.0
    raw = None
    if rates is not None and key in rates:
        raw = rates.get(key)
    if raw is None:
        raw = defaults.get(key, 0)
    try:
        return max(0.0, float(raw or 0))
    except (TypeError, ValueError):
        try:
            return max(0.0, float(defaults.get(key) or 0))
        except (TypeError, ValueError):
            return 0.0


def _hotel_strip_merged_room_rate_folio(stay, keep_source_room_ids=None):
    """Drop auto merged-room-rate folio lines; optionally keep listed source room ids."""
    if not isinstance(stay, dict):
        return stay
    folio = stay.get("folioCharges")
    if not isinstance(folio, list) or not folio:
        return stay
    keep = None
    if keep_source_room_ids is not None:
        keep = {str(x).strip() for x in keep_source_room_ids if str(x).strip()}
    next_folio = []
    for line in folio:
        if not isinstance(line, dict):
            next_folio.append(line)
            continue
        if str(line.get("source") or "") != "merged_room_rate":
            next_folio.append(line)
            continue
        src = str(line.get("sourceRoomId") or "").strip()
        if keep is not None and src in keep:
            next_folio.append(line)
    stay["folioCharges"] = next_folio
    return stay


def _hotel_sync_merged_room_rate_folio(primary, rooms, tariff_rates=None):
    """Ensure primary folio has one rate×nights line per merge member.

    Skips members that already have an absorb line (source=room_merge) so occupied
    merges are not double-counted. Upserts source=merged_room_rate lines from the
    stay's typed mergeRoomRates only — never invent Hotel Settings tariffs.
    """
    if not isinstance(primary, dict) or not primary.get("mergePrimary"):
        return
    if primary.get("stay") and isinstance(primary.get("stay"), dict):
        if primary["stay"].get("invoiceGenerated") or primary["stay"].get("invoiceNumber"):
            return
    group_id = _hotel_room_merge_group_id(primary)
    if not group_id:
        return
    peers = _hotel_rooms_in_merge_group(rooms, group_id)
    members = [
        peer
        for peer in peers
        if isinstance(peer, dict) and peer.get("id") != primary.get("id")
    ]
    primary_stay = (
        dict(primary.get("stay"))
        if isinstance(primary.get("stay"), dict)
        else {}
    )
    if not members:
        _hotel_strip_merged_room_rate_folio(primary_stay, keep_source_room_ids=set())
        primary["stay"] = _normalize_hotel_room_stay(primary_stay)
        return

    folio = list(primary_stay.get("folioCharges") or [])
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    member_ids = {str(m.get("id") or "").strip() for m in members if m.get("id")}
    rate_rows = [
        row for row in (primary_stay.get("mergeRoomRates") or []) if isinstance(row, dict)
    ]
    try:
        nights = max(1, int(float(primary_stay.get("nights") or 1)))
    except (TypeError, ValueError):
        nights = 1
    overstay = _hotel_overstay_extra_nights(primary_stay)
    billable = max(1, nights + overstay)
    try:
        primary_rate = max(0.0, float(primary_stay.get("roomRate") or 0))
    except (TypeError, ValueError):
        primary_rate = 0.0
    primary_type = str(primary.get("roomType") or "").strip()
    primary_plan = str(primary_stay.get("ratePlan") or "").strip()
    # Vacant merge shells must not get auto folio lines (that would flip status to Occupied).
    billable_stay = bool(
        primary_rate > 0
        or primary_stay.get("checkInDate")
        or primary_stay.get("checkedInAt")
        or primary_stay.get("firstName")
        or primary_stay.get("lastName")
        or primary_stay.get("guestName")
        or primary_stay.get("mobile")
    )

    def _lookup_saved_row(room_id, number):
        rid = str(room_id or "").strip()
        num = str(number or "").strip()
        for row in rate_rows:
            if rid and str(row.get("roomId") or "").strip() == rid:
                return row
            if num and str(row.get("number") or "").strip() == num:
                return row
        return None

    def _lookup_saved_rate(room_id, number):
        row = _lookup_saved_row(room_id, number)
        if row is None:
            return None, False
        try:
            return max(0.0, float(row.get("roomRate") or 0)), True
        except (TypeError, ValueError):
            return 0.0, True

    def _row_charges(row, fallback_nightly):
        """Total stay charges for a merge room rate row."""
        if isinstance(row, dict):
            summed = _hotel_sum_nightly_rates(row.get("nightlyRates"))
            if summed is not None:
                return summed
            try:
                rate = max(0.0, float(row.get("roomRate") or fallback_nightly or 0))
            except (TypeError, ValueError):
                rate = max(0.0, float(fallback_nightly or 0))
            return round(rate * billable, 2)
        try:
            rate = max(0.0, float(fallback_nightly or 0))
        except (TypeError, ValueError):
            rate = 0.0
        return round(rate * billable, 2)

    def _nightly_rates_for(room, default_rate, default_plan):
        rid = str(room.get("id") or "").strip()
        num = str(room.get("number") or "").strip()
        saved = _lookup_saved_row(rid, num)
        raw = (saved or {}).get("nightlyRates") if isinstance(saved, dict) else None
        if not isinstance(raw, list) or not raw:
            return []
        return _hotel_normalize_nightly_rates(
            raw,
            check_in=primary_stay.get("checkInDate"),
            nights=nights,
            overstay_nights=overstay,
            default_rate=default_rate,
            default_plan=default_plan,
        )

    def _nightly_rate_for(room, *, is_primary=False):
        rid = str(room.get("id") or "").strip()
        num = str(room.get("number") or "").strip()
        saved, has_saved = _lookup_saved_rate(rid, num)
        if has_saved and saved is not None:
            return saved
        if is_primary and primary_rate > 0:
            return primary_rate
        return 0.0

    def _has_absorb(source_room_id):
        sid = str(source_room_id or "").strip()
        for line in folio:
            if not isinstance(line, dict):
                continue
            if str(line.get("source") or "") != "room_merge":
                continue
            if str(line.get("sourceRoomId") or "").strip() == sid:
                return True
        return False

    def _find_rate_line_index(source_room_id):
        sid = str(source_room_id or "").strip()
        for idx, line in enumerate(folio):
            if not isinstance(line, dict):
                continue
            if str(line.get("source") or "") != "merged_room_rate":
                continue
            if str(line.get("sourceRoomId") or "").strip() == sid:
                return idx
        return -1

    # Keep mergeRoomRates in sync so Estimated Charges / re-edits use per-room tariffs.
    next_rate_rows = []
    primary_nightly = _nightly_rate_for(primary, is_primary=True)
    primary_nightly_rows = _nightly_rates_for(primary, primary_nightly, primary_plan)
    primary_row = {
        "roomId": str(primary.get("id") or ""),
        "number": str(primary.get("number") or "").strip(),
        "roomType": primary_type,
        "roomTypeLabel": str(
            primary.get("roomTypeLabel") or primary_type or ""
        ).strip(),
        "ratePlan": (
            primary_nightly_rows[0]["ratePlan"]
            if primary_nightly_rows
            else primary_plan
        ),
        "roomRate": (
            primary_nightly_rows[0]["roomRate"]
            if primary_nightly_rows
            else round(primary_nightly, 2)
        ),
        "isPrimary": True,
        "nightlyRates": primary_nightly_rows,
    }
    next_rate_rows.append(primary_row)
    for member in members:
        mid = str(member.get("id") or "").strip()
        mnum = str(member.get("number") or "").strip()
        mtype = str(member.get("roomType") or "").strip()
        member_nightly = _nightly_rate_for(member)
        saved_plan = primary_plan
        for row in rate_rows:
            if mid and str(row.get("roomId") or "").strip() == mid:
                saved_plan = str(row.get("ratePlan") or saved_plan).strip() or saved_plan
                break
            if mnum and str(row.get("number") or "").strip() == mnum:
                saved_plan = str(row.get("ratePlan") or saved_plan).strip() or saved_plan
                break
        member_nightly_rows = _nightly_rates_for(member, member_nightly, saved_plan)
        next_rate_rows.append(
            {
                "roomId": mid,
                "number": mnum,
                "roomType": mtype,
                "roomTypeLabel": str(
                    member.get("roomTypeLabel") or mtype or ""
                ).strip(),
                "ratePlan": (
                    member_nightly_rows[0]["ratePlan"]
                    if member_nightly_rows
                    else saved_plan
                ),
                "roomRate": (
                    member_nightly_rows[0]["roomRate"]
                    if member_nightly_rows
                    else round(member_nightly, 2)
                ),
                "isPrimary": False,
                "nightlyRates": member_nightly_rows,
            }
        )
    primary_stay["mergeRoomRates"] = next_rate_rows
    if primary_nightly_rows and not (
        isinstance(primary_stay.get("nightlyRates"), list)
        and primary_stay.get("nightlyRates")
    ):
        primary_stay["nightlyRates"] = list(primary_nightly_rows)
        primary_stay["roomRate"] = primary_row["roomRate"]
        primary_stay["ratePlan"] = primary_row["ratePlan"]
    rate_rows = next_rate_rows

    if not billable_stay:
        _hotel_strip_merged_room_rate_folio(primary_stay, keep_source_room_ids=set())
        primary["stay"] = _normalize_hotel_room_stay(primary_stay)
        return

    # Drop stale merged_room_rate lines for rooms no longer in the group.
    folio = [
        line
        for line in folio
        if not (
            isinstance(line, dict)
            and str(line.get("source") or "") == "merged_room_rate"
            and str(line.get("sourceRoomId") or "").strip() not in member_ids
        )
    ]

    for member in members:
        mid = str(member.get("id") or "").strip()
        if not mid:
            continue
        if _has_absorb(mid):
            # Occupied absorb already billed this room — refresh amount only when
            # mergeRoomRates carry a real tariff; otherwise keep the absorb line.
            number = str(member.get("number") or "").strip() or mid
            member_row = _lookup_saved_row(mid, number)
            amount = _row_charges(member_row, _nightly_rate_for(member))
            absorb_idx = -1
            for idx, line in enumerate(folio):
                if not isinstance(line, dict):
                    continue
                if str(line.get("source") or "") != "room_merge":
                    continue
                if str(line.get("sourceRoomId") or "").strip() != mid:
                    continue
                absorb_idx = idx
                break
            if absorb_idx >= 0 and amount > 0.009:
                line = dict(folio[absorb_idx])
                line["label"] = f"Room {number} — stay charges"
                line["amount"] = amount
                line["sourceRoomNumber"] = number
                folio[absorb_idx] = line
            idx = _find_rate_line_index(mid)
            if idx >= 0:
                folio.pop(idx)
            continue
        number = str(member.get("number") or "").strip() or mid
        label = f"Room {number} — stay charges"
        idx = _find_rate_line_index(mid)
        member_row = _lookup_saved_row(mid, number)
        amount = _row_charges(member_row, _nightly_rate_for(member))
        if amount <= 0:
            if idx >= 0:
                folio.pop(idx)
            continue
        if idx >= 0:
            line = dict(folio[idx])
            line["label"] = label
            line["amount"] = amount
            line["sourceRoomNumber"] = number
            folio[idx] = line
        else:
            folio.append(
                {
                    "id": f"mrr-{mid}-{stamp.replace(' ', '')}",
                    "kind": "other",
                    "label": label,
                    "amount": amount,
                    "source": "merged_room_rate",
                    "invoiceId": "",
                    "outlet": "",
                    "at": stamp,
                    "note": f"Merged room rate for Room {number}",
                    "sourceRoomId": mid,
                    "sourceRoomNumber": number,
                }
            )

    primary_stay["folioCharges"] = folio
    primary["stay"] = _normalize_hotel_room_stay(primary_stay)


def _hotel_stay_room_charge_amount(stay):
    stay = stay if isinstance(stay, dict) else {}
    try:
        nights = max(1, int(float(stay.get("nights") or 1)))
    except (TypeError, ValueError):
        nights = 1
    overstay = _hotel_overstay_extra_nights(stay)
    billable = max(1, nights + overstay)
    try:
        rate = float(stay.get("roomRate") or 0)
    except (TypeError, ValueError):
        rate = 0.0
    extras = 0.0
    for key in ("extraBedAmount", "earlyCheckinAmount", "lateCheckoutAmount"):
        try:
            extras += float(stay.get(key) or 0)
        except (TypeError, ValueError):
            pass
    return round(rate * billable + extras, 2)


def enrich_hotel_room_merge_fields(room, rooms=None):
    """Attach merge display helpers onto a room dict (mutates a copy-friendly dict)."""
    if not isinstance(room, dict):
        return room
    result = room
    group_id = _hotel_room_merge_group_id(result)
    stay = result.get("stay") if isinstance(result.get("stay"), dict) else {}
    billing_id = str(stay.get("billingRoomId") or "").strip()
    is_member = bool(stay.get("mergeRole") == "member" or billing_id)
    is_primary = bool(group_id and result.get("mergePrimary") and not is_member)
    result["isMergeMember"] = is_member
    result["isMergePrimary"] = is_primary
    result["billingRoomId"] = billing_id or (result.get("id") if is_primary else "")
    result["billingRoomNumber"] = ""
    result["mergeLabel"] = ""
    result["mergePartnerNumbers"] = []
    result["mergePartners"] = []
    if not group_id and not is_member:
        return result
    peers = _hotel_rooms_in_merge_group(rooms, group_id) if rooms is not None else []
    if rooms is None and group_id:
        # Caller didn't pass layout rooms — leave partners empty.
        peers = [result]
    numbers = []
    primary_number = ""
    for peer in peers:
        num = str(peer.get("number") or "").strip()
        if num:
            numbers.append(num)
        if peer.get("mergePrimary"):
            primary_number = num or primary_number
        if billing_id and (
            peer.get("id") == billing_id or peer.get("number") == billing_id
        ):
            result["billingRoomNumber"] = num
    if is_primary:
        result["billingRoomNumber"] = str(result.get("number") or "")
        partners = [n for n in numbers if n != str(result.get("number") or "")]
        result["mergePartnerNumbers"] = partners
        partner_rows = []
        for peer in peers:
            if not isinstance(peer, dict):
                continue
            if peer.get("id") == result.get("id"):
                continue
            partner_rows.append(
                {
                    "id": peer.get("id") or "",
                    "number": str(peer.get("number") or "").strip(),
                    "roomType": peer.get("roomType") or "",
                    "roomTypeLabel": peer.get("roomTypeLabel")
                    or peer.get("roomType")
                    or "",
                }
            )
        result["mergePartners"] = partner_rows
        if partners:
            result["mergeLabel"] = f"{result.get('number')} + {' + '.join(partners)}"
        else:
            result["mergeLabel"] = str(result.get("number") or "")
    elif is_member:
        if not result["billingRoomNumber"] and primary_number:
            result["billingRoomNumber"] = primary_number
        result["mergePartnerNumbers"] = [
            n for n in numbers if n != str(result.get("number") or "")
        ]
        bill = result.get("billingRoomNumber") or primary_number or "—"
        result["mergeLabel"] = f"Bill: {bill}"
    if rooms is not None and (is_member or is_primary):
        _hotel_overlay_merge_shared_bill_view(result, rooms)
    return result


def _hotel_snapshot_merge_rooms_on_stay(room, rooms=None):
    """Persist merged room numbers onto the stay for invoice/print after demerge.

    Prefer live merge peers when available; otherwise keep an existing snapshot.
    """
    if not isinstance(room, dict):
        return room
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if not stay:
        return room
    stay = dict(stay)
    primary_num = _hotel_str(room.get("number"), 20)
    numbers = []
    enriched = enrich_hotel_room_merge_fields(dict(room), rooms)
    partners = list(enriched.get("mergePartnerNumbers") or [])
    if primary_num:
        numbers.append(primary_num)
    for partner in partners:
        num = _hotel_str(partner, 20)
        if num and num not in numbers:
            numbers.append(num)
    if len(numbers) <= 1:
        existing = stay.get("mergeRoomNumbers") or stay.get("merge_room_numbers") or []
        if isinstance(existing, (list, tuple)) and len(existing) > 1:
            numbers = []
            for item in existing[:20]:
                num = _hotel_str(item, 20)
                if num and num not in numbers:
                    numbers.append(num)
        elif stay.get("mergeRoomLabel") or stay.get("merge_room_label"):
            # Keep prior label/numbers if still present after normalize.
            room["stay"] = stay
            return room
    if len(numbers) > 1:
        stay["mergeRoomNumbers"] = numbers
        stay["mergeRoomLabel"] = " + ".join(numbers)
    room["stay"] = stay
    return room


def merge_hotel_room_billing(conn, from_room_id, to_room_id, note=""):
    """Combine two rooms onto ``to_room_id`` as the billing primary.

    Any rooms may be merged (vacant included). Folio/payments/room charges from
    the member (from) move onto the primary (to) when a stay exists.
    Unmerge later splits those tagged charges back onto each room.
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    source = _hotel_find_room(rooms, from_room_id)
    primary = _hotel_find_room(rooms, to_room_id)
    if not source:
        raise ValueError("Source room not found.")
    if not primary:
        raise ValueError("Destination room not found.")
    if source.get("id") == primary.get("id"):
        raise ValueError("Choose two different rooms to merge.")
    source_stay = source.get("stay") if isinstance(source.get("stay"), dict) else None
    primary_stay = primary.get("stay") if isinstance(primary.get("stay"), dict) else None
    if source_stay and (
        source_stay.get("mergeRole") == "member" or source_stay.get("billingRoomId")
    ):
        raise ValueError(
            f"Room {source.get('number')} is already billed with another room. Unmerge it first."
        )
    if primary_stay and (
        primary_stay.get("mergeRole") == "member" or primary_stay.get("billingRoomId")
    ):
        raise ValueError(
            f"Room {primary.get('number')} is a merge member. Make it primary or unmerge first."
        )
    if source.get("mergePrimary") is False and _hotel_room_merge_group_id(source):
        raise ValueError(
            f"Room {source.get('number')} is already billed with another room. Unmerge it first."
        )
    if primary.get("mergePrimary") is False and _hotel_room_merge_group_id(primary):
        raise ValueError(
            f"Room {primary.get('number')} is a merge member. Make it primary or unmerge first."
        )

    # Primary always holds the shared bill — create an empty stay shell if needed.
    if not primary_stay:
        primary_stay = _normalize_hotel_room_stay({})
    else:
        primary_stay = _normalize_hotel_room_stay(primary_stay)
    primary_stay["independentBilling"] = False
    if source_stay:
        source_stay = _normalize_hotel_room_stay(source_stay)
        source_stay["independentBilling"] = False

    # Absorb existing primary group if any; reject if source is already a different primary with members
    # without absorbing — we absorb source's group members onto this primary too.
    source_group = _hotel_room_merge_group_id(source)
    primary_group = _hotel_room_merge_group_id(primary)
    absorb_ids = {str(source.get("id"))}
    if source_group:
        for r in _hotel_rooms_in_merge_group(rooms, source_group):
            absorb_ids.add(str(r.get("id")))
    if primary_group:
        for r in _hotel_rooms_in_merge_group(rooms, primary_group):
            absorb_ids.add(str(r.get("id")))

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    note_text = _hotel_str(note, 200)
    folio = list(primary_stay.get("folioCharges") or [])
    payments = list(primary_stay.get("payments") or [])

    def _absorb_member_charges(member_room, member_stay):
        nonlocal folio, payments, primary_stay
        if member_room.get("id") == primary.get("id"):
            return
        member_stay = _normalize_hotel_room_stay(member_stay)
        if member_stay.get("mergeRole") == "member":
            # Already stripped — just re-link.
            return
        room_charge = _hotel_stay_room_charge_amount(member_stay)
        for line in member_stay.get("folioCharges") or []:
            moved = dict(line)
            moved["sourceRoomId"] = member_room.get("id") or ""
            moved["sourceRoomNumber"] = member_room.get("number") or ""
            existing_note = moved.get("note") or ""
            tag = f"Merged from Room {member_room.get('number')}"
            moved["note"] = (existing_note + " | " if existing_note else "") + tag
            moved["note"] = moved["note"][:200]
            folio.append(moved)
        if room_charge > 0:
            folio.append(
                {
                    "id": f"mrg-{member_room.get('id')}-{stamp.replace(' ', '')}",
                    "kind": "other",
                    "label": f"Room {member_room.get('number')} — stay charges",
                    "amount": room_charge,
                    "source": "room_merge",
                    "invoiceId": "",
                    "outlet": "",
                    "at": stamp,
                    "note": note_text or f"Merged from Room {member_room.get('number')}",
                    "sourceRoomId": member_room.get("id") or "",
                    "sourceRoomNumber": member_room.get("number") or "",
                }
            )
        for pay in member_stay.get("payments") or []:
            payments.append(dict(pay))
        # Fold check-in advance into primary check-in advance.
        try:
            member_adv = float(member_stay.get("checkInAdvancePaid") or 0)
        except (TypeError, ValueError):
            member_adv = 0.0
        try:
            primary_adv = float(primary_stay.get("checkInAdvancePaid") or 0)
        except (TypeError, ValueError):
            primary_adv = 0.0
        if member_adv > 0:
            primary_stay["checkInAdvancePaid"] = round(primary_adv + member_adv, 2)

    # Absorb every non-primary room in the combined set.
    for rid in list(absorb_ids):
        member_room = _hotel_find_room(rooms, rid)
        if not member_room or member_room.get("id") == primary.get("id"):
            continue
        mstay = member_room.get("stay") if isinstance(member_room.get("stay"), dict) else None
        if not mstay:
            continue
        # If this room was already a member of primary's group, skip charge move.
        if (
            _hotel_room_merge_group_id(member_room) == primary_group
            and primary_group
            and not member_room.get("mergePrimary")
        ):
            continue
        _absorb_member_charges(member_room, mstay)

    primary_stay["folioCharges"] = folio
    primary_stay["payments"] = payments
    primary_stay["mergeRole"] = "primary"
    primary_stay["billingRoomId"] = ""

    # Fill missing guest / stay-window fields from absorbed members.
    for rid in list(absorb_ids):
        member_room = _hotel_find_room(rooms, rid)
        if not member_room or member_room.get("id") == primary.get("id"):
            continue
        mstay = member_room.get("stay") if isinstance(member_room.get("stay"), dict) else None
        if not mstay:
            continue
        for key in (
            "title",
            "firstName",
            "lastName",
            "guestName",
            "mobile",
            "mobileCountry",
            "email",
            "address",
            "city",
            "state",
            "country",
            "pin",
            "idType",
            "idNumber",
            "agencyName",
            "agencyGst",
            "agencyAddress",
            "agencyBilling",
            "agencyRoomBilling",
            "agencyFbBilling",
            "invoiceTo",
            "billingName",
            "checkInDate",
            "checkInTime",
            "checkOutDate",
            "checkOutTime",
            "nights",
            "adults",
            "children",
            "bookingNumber",
            "bookingDate",
        ):
            if not primary_stay.get(key) and mstay.get(key) not in (None, "", [], {}):
                primary_stay[key] = mstay.get(key)

    primary_stay = _normalize_hotel_room_stay(primary_stay)
    primary["stay"] = primary_stay

    group_id = primary_group or source_group or _new_hotel_merge_group_id()
    primary["mergeGroupId"] = group_id
    primary["mergePrimary"] = True

    for rid in absorb_ids:
        member_room = _hotel_find_room(rooms, rid)
        if not member_room:
            continue
        if member_room.get("id") == primary.get("id"):
            continue
        mstay = member_room.get("stay") if isinstance(member_room.get("stay"), dict) else {}
        member_room["stay"] = _hotel_member_stay_from_occupied(mstay, primary.get("id"))
        member_room["mergeGroupId"] = group_id
        member_room["mergePrimary"] = False
        # Reservation assigns merge vacant peers onto a reserved primary — keep
        # inventory aligned so check-in / board treat every linked room as reserved.
        if _normalize_hotel_room_status(primary.get("status")) == "reserved":
            member_room["status"] = "reserved"

    _hotel_sync_merge_group_shared_data(
        rooms, tariff_rates=get_hotel_tariff_rates(conn)
    )
    _hotel_snapshot_merge_rooms_on_stay(primary, rooms)

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    primary_out = get_hotel_room(conn, primary.get("id"))
    source_out = get_hotel_room(conn, source.get("id"))
    if primary_out:
        enrich_hotel_room_merge_fields(primary_out, saved.get("rooms"))
    if source_out:
        enrich_hotel_room_merge_fields(source_out, saved.get("rooms"))
    return {
        "primaryRoom": primary_out,
        "memberRoom": source_out,
        "room": primary_out,
        "layout": saved,
    }


def ensure_hotel_reservation_merge_groups(conn):
    """Join occupied/reserved rooms that share a reservation id into one merge group.

    Occupancy is unchanged. Returns True when at least one merge was applied.
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    by_rid = {}
    for room in rooms:
        if not isinstance(room, dict):
            continue
        status = _normalize_hotel_room_status(room.get("status"))
        if status not in ("occupied", "reserved"):
            continue
        stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
        rid = _hotel_stay_reservation_id(stay)
        if not rid:
            continue
        if _hotel_stay_independent_billing(stay):
            continue
        room_id = str(room.get("id") or "").strip()
        if not room_id:
            continue
        by_rid.setdefault(rid, []).append(room_id)

    merged_any = False
    for rid, room_ids in by_rid.items():
        if len(room_ids) < 2:
            continue
        safety = 0
        while safety < len(room_ids) + 2:
            safety += 1
            layout = get_hotel_rooms_layout(conn)
            rooms = layout.get("rooms") or []
            peers = _hotel_rooms_sharing_reservation(rooms, rid)
            if len(peers) < 2:
                break
            gids = {_hotel_room_merge_group_id(p) for p in peers}
            gids.discard("")
            if len(gids) == 1 and all(_hotel_room_merge_group_id(p) for p in peers):
                break
            primary = _hotel_pick_reservation_merge_primary(rooms, peers)
            if not primary:
                break
            if _hotel_room_is_merge_member(primary):
                billed = _hotel_billing_primary_for_room(rooms, primary)
                if billed:
                    primary = billed
            pgid = _hotel_room_merge_group_id(primary)
            source = None
            for peer in peers:
                if str(peer.get("id") or "") == str(primary.get("id") or ""):
                    continue
                if pgid and _hotel_room_merge_group_id(peer) == pgid:
                    continue
                candidate = peer
                if _hotel_room_is_merge_member(peer):
                    billed = _hotel_billing_primary_for_room(rooms, peer)
                    if billed:
                        candidate = billed
                if str(candidate.get("id") or "") == str(primary.get("id") or ""):
                    continue
                source = candidate
                break
            if not source:
                break
            try:
                merge_hotel_room_billing(
                    conn,
                    from_room_id=source.get("id"),
                    to_room_id=primary.get("id"),
                )
                merged_any = True
            except ValueError:
                break
    return merged_any


def _hotel_clean_unmerged_folio_line(line):
    """Strip merge tags so a moved folio line is a normal charge on this room."""
    cleaned = dict(line) if isinstance(line, dict) else {}
    note = str(cleaned.get("note") or "")
    note = re.sub(r"(?:\s*\|\s*)?Merged from Room\s+\S+", "", note, flags=re.I)
    cleaned["note"] = note.strip(" |")[:200]
    src = str(cleaned.get("source") or "").strip()
    if src in ("room_merge", "merged_room_rate"):
        cleaned["source"] = "unmerged_stay"
    cleaned["sourceRoomId"] = ""
    cleaned["sourceRoomNumber"] = ""
    return cleaned


def _hotel_apply_merge_rate_row_to_member(primary_stay, member):
    """Copy a mergeRoomRates row onto the member when it has no roomRate."""
    if not isinstance(member, dict) or not isinstance(primary_stay, dict):
        return
    mstay = member.get("stay") if isinstance(member.get("stay"), dict) else {}
    mstay = dict(mstay)
    try:
        current = float(mstay.get("roomRate") or 0)
    except (TypeError, ValueError):
        current = 0.0
    if current > 0:
        return
    rid = str(member.get("id") or "").strip()
    for row in primary_stay.get("mergeRoomRates") or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("roomId") or "").strip() != rid:
            continue
        try:
            rate = float(row.get("roomRate") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        if rate > 0:
            mstay["roomRate"] = rate
            if row.get("ratePlan"):
                mstay["ratePlan"] = row.get("ratePlan")
            nights = row.get("nightlyRates")
            if isinstance(nights, list) and nights:
                mstay["nightlyRates"] = list(nights)
            member["stay"] = mstay
        break


def _hotel_restore_unmerged_billing(primary, member):
    """Move this member's tagged charges off the shared folio onto the member stay."""
    if not isinstance(primary, dict) or not isinstance(member, dict):
        return
    if str(primary.get("id") or "") == str(member.get("id") or ""):
        return
    pstay = primary.get("stay") if isinstance(primary.get("stay"), dict) else None
    if not pstay:
        return
    pstay = dict(pstay)
    mstay = member.get("stay") if isinstance(member.get("stay"), dict) else {}
    mstay = dict(mstay)
    rid = str(member.get("id") or "").strip()
    kept = []
    extra_folio = []
    for line in pstay.get("folioCharges") or []:
        if not isinstance(line, dict):
            kept.append(line)
            continue
        if str(line.get("sourceRoomId") or "").strip() != rid:
            kept.append(line)
            continue
        src = str(line.get("source") or "").strip()
        if src in ("room_merge", "merged_room_rate"):
            _hotel_apply_merge_rate_row_to_member(pstay, member)
            mstay = (
                dict(member["stay"])
                if isinstance(member.get("stay"), dict)
                else mstay
            )
            continue
        extra_folio.append(_hotel_clean_unmerged_folio_line(line))
    pstay["folioCharges"] = kept
    pstay["mergeRoomRates"] = [
        row
        for row in (pstay.get("mergeRoomRates") or [])
        if not (
            isinstance(row, dict) and str(row.get("roomId") or "").strip() == rid
        )
    ]
    existing = [
        dict(item)
        for item in (mstay.get("folioCharges") or [])
        if isinstance(item, dict)
    ]
    mstay["folioCharges"] = existing + extra_folio
    primary["stay"] = pstay
    member["stay"] = mstay


def _hotel_finalize_independent_room(room, tax_rates=None):
    """Clear merge links and keep this room on its own bill."""
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else None
    if stay:
        stay = dict(stay)
        stay["independentBilling"] = True
        stay["billingRoomId"] = ""
        stay["mergeRole"] = ""
        stay["mergeRoomNumbers"] = []
        stay["mergeRoomLabel"] = ""
        stay["mergeRoomRates"] = []
        room["stay"] = _normalize_hotel_room_stay(stay, tax_rates=tax_rates)
    _hotel_clear_room_merge_fields(room)


def unmerge_hotel_rooms(conn, room_id, scope="one"):
    """Split a room (or the whole group) onto individual bills."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    room = _hotel_find_room(rooms, room_id)
    if not room:
        raise ValueError("Room not found.")
    group_id = _hotel_room_merge_group_id(room)
    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
    if not group_id and not stay.get("billingRoomId") and stay.get("mergeRole") != "member":
        raise ValueError("Room is not part of a merge group.")

    tax_rates = get_hotel_tax_rates(conn)
    tariff_rates = get_hotel_tariff_rates(conn)
    scope_key = str(scope or "one").strip().lower()
    was_primary = bool(room.get("mergePrimary"))
    # Unmerging the billing primary must dissolve the whole group. Clearing only
    # the primary leaves members with mergeRole=member, which hides them on the board.
    dissolve_group = scope_key in ("group", "all", "everything") or (
        was_primary and bool(group_id)
    )

    def _group_primary():
        if not group_id:
            return room if was_primary else None
        for peer in _hotel_rooms_in_merge_group(rooms, group_id):
            if peer.get("mergePrimary"):
                return peer
        return room if was_primary else None

    if dissolve_group:
        targets = _hotel_rooms_in_merge_group(rooms, group_id) if group_id else [room]
        primary_peer = _group_primary()
        if primary_peer:
            for peer in targets:
                if peer.get("id") == primary_peer.get("id"):
                    continue
                _hotel_restore_unmerged_billing(primary_peer, peer)
            primary_peer["stay"] = _normalize_hotel_room_stay(
                primary_peer.get("stay") or {}, tax_rates=tax_rates
            )
        for peer in targets:
            _hotel_finalize_independent_room(peer, tax_rates=tax_rates)
    else:
        primary_peer = _group_primary()
        if primary_peer:
            _hotel_restore_unmerged_billing(primary_peer, room)
            primary_peer["stay"] = _normalize_hotel_room_stay(
                primary_peer.get("stay") or {}, tax_rates=tax_rates
            )
        _hotel_finalize_independent_room(room, tax_rates=tax_rates)
        remaining = _hotel_rooms_in_merge_group(rooms, group_id) if group_id else []
        if len(remaining) <= 1:
            for peer in remaining:
                _hotel_finalize_independent_room(peer, tax_rates=tax_rates)
        else:
            _hotel_sync_merge_group_shared_data(rooms, tariff_rates=tariff_rates)
            if primary_peer:
                _hotel_snapshot_merge_rooms_on_stay(primary_peer, rooms)

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    out = get_hotel_room(conn, room.get("id"))
    if out:
        enrich_hotel_room_merge_fields(out, saved.get("rooms"))
    return {"room": out, "layout": saved}


def _hotel_pick_merge_primary_successor(peers, exclude_id):
    """Prefer an occupied peer, then reserved, then the richest remaining stay."""
    exclude = str(exclude_id or "").strip()
    candidates = [
        room
        for room in (peers or [])
        if isinstance(room, dict) and str(room.get("id") or "").strip() != exclude
    ]
    if not candidates:
        return None

    def _rank(room):
        status = _normalize_hotel_room_status(room.get("status"))
        occ = 2 if status == "occupied" else 1 if status == "reserved" else 0
        return (occ, _hotel_stay_guest_richness(room.get("stay")))

    return max(candidates, key=_rank)


def _hotel_reassign_merge_primary(rooms, new_primary, old_primary):
    """Move folio/invoice onto new_primary; old_primary becomes a member.

    Occupancy status and checkedInAt stay on each room.
    """
    group_id = _hotel_room_merge_group_id(old_primary) or _hotel_room_merge_group_id(
        new_primary
    )
    old_stay = old_primary.get("stay") if isinstance(old_primary.get("stay"), dict) else {}
    old_stay = _normalize_hotel_room_stay(old_stay)
    new_stay = new_primary.get("stay") if isinstance(new_primary.get("stay"), dict) else {}
    display = _normalize_hotel_room_stay(new_stay)
    guest_keys = (
        "title",
        "firstName",
        "lastName",
        "guestName",
        "gender",
        "dateOfBirth",
        "nationality",
        "mobileCountry",
        "mobile",
        "email",
        "address",
        "city",
        "state",
        "country",
        "pin",
        "purposeOfVisit",
        "vipStatus",
        "returningGuest",
        "idType",
        "idNumber",
        "idIssueDate",
        "idExpiryDate",
        "idPlaceOfIssue",
        "idDocumentName",
        "idDocumentPath",
        "idDocumentMime",
        "idDocumentStoredName",
        "additionalGuests",
        "agencyName",
        "agencyGst",
        "agencyAddress",
        "agencyBilling",
        "agencyRoomBilling",
        "agencyFbBilling",
        "invoiceTo",
        "billingName",
        "profession",
        "company",
        "loyaltyNumber",
        "notes",
        "checkInDate",
        "checkInTime",
        "checkOutDate",
        "checkOutTime",
        "nights",
        "adults",
        "children",
        "ratePlan",
        "roomRate",
        "totalRate",
        "specialRequests",
        "additionalRequests",
        "extraBedQty",
        "extraBedRate",
        "extraBedNights",
        "extraBedAmount",
        "extraBedNote",
        "earlyCheckinQty",
        "earlyCheckinRate",
        "earlyCheckinNights",
        "earlyCheckinAmount",
        "earlyCheckinNote",
        "lateCheckoutQty",
        "lateCheckoutRate",
        "lateCheckoutNights",
        "lateCheckoutAmount",
        "lateCheckoutNote",
        "transferCount",
        "transferHistory",
        "bookingNumber",
        "bookingDate",
    )
    moved = dict(old_stay)
    for key in guest_keys:
        val = display.get(key)
        if val not in (None, "", [], {}):
            moved[key] = val
    own_checked_in = display.get("checkedInAt") or display.get("checked_in_at")
    if own_checked_in:
        moved["checkedInAt"] = own_checked_in
    else:
        moved.pop("checkedInAt", None)
        moved.pop("checked_in_at", None)
    moved["billingRoomId"] = ""
    moved["mergeRole"] = "primary"
    moved_stay = _normalize_hotel_room_stay(moved)
    if moved_stay.get("invoiceGenerated") and moved_stay.get("invoiceNumber"):
        # Successor inherits an already-minted merge bill — lock snapshots so
        # date overstay does not surface as "Generate Additional Room Invoice".
        moved_stay = _normalize_hotel_room_stay(
            _hotel_lock_invoiced_snapshots_to_current(moved_stay)
        )
    new_primary["stay"] = moved_stay
    new_primary["mergeGroupId"] = group_id
    new_primary["mergePrimary"] = True

    old_primary["stay"] = _hotel_member_stay_from_occupied(old_stay, new_primary.get("id"))
    old_primary["mergeGroupId"] = group_id
    old_primary["mergePrimary"] = False

    for peer in _hotel_rooms_in_merge_group(rooms, group_id):
        if peer.get("id") in (new_primary.get("id"), old_primary.get("id")):
            continue
        pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else {}
        pstay = dict(pstay)
        pstay["billingRoomId"] = new_primary.get("id")
        pstay["mergeRole"] = "member"
        peer["stay"] = _normalize_hotel_room_stay(pstay)
        peer["mergePrimary"] = False
    _hotel_stamp_merge_peers_billed_invoice(rooms, new_primary)
    return old_stay


def set_hotel_merge_primary(conn, room_id):
    """Make an occupied merge member the new billing primary; move folio/invoice."""
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    new_primary = _hotel_find_room(rooms, room_id)
    if not new_primary:
        raise ValueError("Room not found.")
    group_id = _hotel_room_merge_group_id(new_primary)
    if not group_id:
        raise ValueError("Room is not part of a merge group.")
    if _normalize_hotel_room_status(new_primary.get("status")) != "occupied":
        raise ValueError("Only occupied rooms can become the billing primary.")
    new_stay = new_primary.get("stay") if isinstance(new_primary.get("stay"), dict) else None
    if not new_stay:
        raise ValueError("Room has no active stay.")
    if new_primary.get("mergePrimary") and new_stay.get("mergeRole") != "member":
        return {"room": get_hotel_room(conn, new_primary.get("id")), "layout": layout}

    old_primary = None
    for peer in _hotel_rooms_in_merge_group(rooms, group_id):
        if peer.get("mergePrimary"):
            old_primary = peer
            break
    if not old_primary:
        raise ValueError("Could not find the current billing primary.")
    if old_primary.get("id") == new_primary.get("id"):
        return {"room": get_hotel_room(conn, new_primary.get("id")), "layout": layout}

    old_stay = _hotel_reassign_merge_primary(rooms, new_primary, old_primary)

    if old_stay.get("invoiceNumber"):
        upsert_hotel_room_invoice_from_room(conn, new_primary)

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    out = get_hotel_room(conn, new_primary.get("id"))
    if out:
        enrich_hotel_room_merge_fields(out, saved.get("rooms"))
    return {"room": out, "layout": saved}


def clear_hotel_room_stay(conn, room_id, status="dirty"):
    """Clear stay data and set post-checkout status for this room only.

    Member checkout unmerges that room, then clears it (primary bill unchanged).
    Primary checkout promotes a remaining peer when the group continues, then
    clears this room. Other merged / same-reservation rooms stay as they are.
    Billing stays must already have a generated invoice.
    """
    require_hotel_room_invoice_for_checkout(conn, room_id)
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = _hotel_find_room(rooms, room_id)
    if not target:
        raise ValueError("Room not found.")

    group_id = _hotel_room_merge_group_id(target)
    stay = target.get("stay") if isinstance(target.get("stay"), dict) else None
    is_member = bool(
        stay and (stay.get("mergeRole") == "member" or stay.get("billingRoomId"))
    )
    is_primary = bool(group_id and target.get("mergePrimary") and not is_member)

    if is_primary and group_id:
        peers = _hotel_rooms_in_merge_group(rooms, group_id)
        successor = _hotel_pick_merge_primary_successor(peers, target.get("id"))
        if successor:
            old_stay = _hotel_reassign_merge_primary(rooms, successor, target)
            if old_stay.get("invoiceNumber"):
                upsert_hotel_room_invoice_from_room(conn, successor)
            stay = target.get("stay") if isinstance(target.get("stay"), dict) else None
            is_member = True
            is_primary = False

    if is_member:
        # Leave shared bill; drop this room from the group first.
        if stay:
            stay = dict(stay)
            stay["billingRoomId"] = ""
            stay["mergeRole"] = ""
            target["stay"] = stay
        _hotel_clear_room_merge_fields(target)
        remaining = _hotel_rooms_in_merge_group(rooms, group_id) if group_id else []
        if len(remaining) <= 1:
            for peer in remaining:
                pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
                if pstay:
                    pstay = dict(pstay)
                    pstay["billingRoomId"] = ""
                    pstay["mergeRole"] = ""
                    peer["stay"] = pstay
                _hotel_clear_room_merge_fields(peer)

    stay = target.get("stay") if isinstance(target.get("stay"), dict) else None
    if stay:
        sync_pos_room_transfer_invoices_for_stay(conn, target)
    if stay and (stay.get("invoiceNumber") or stay.get("invoice_number")):
        upsert_hotel_room_invoice_from_room(conn, target)
    upcoming = (
        target.get("upcomingStay")
        if isinstance(target.get("upcomingStay"), dict)
        else (
            target.get("upcoming_stay")
            if isinstance(target.get("upcoming_stay"), dict)
            else None
        )
    )
    target.pop("stay", None)
    _hotel_clear_room_merge_fields(target)
    if upcoming:
        target["stay"] = _normalize_hotel_room_stay(dict(upcoming))
        if not target["stay"].get("bookingNumber"):
            target["stay"]["bookingNumber"] = (
                f"BK{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
        target["status"] = "reserved"
        target.pop("upcomingStay", None)
        target.pop("upcoming_stay", None)
    else:
        target.pop("upcomingStay", None)
        target.pop("upcoming_stay", None)
        target["status"] = _normalize_hotel_room_status(status)
    return save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)


def _hotel_upcoming_stay_dict(room):
    if not isinstance(room, dict):
        return None
    upcoming = room.get("upcomingStay")
    if not isinstance(upcoming, dict):
        upcoming = room.get("upcoming_stay")
    return dict(upcoming) if isinstance(upcoming, dict) else None


def _hotel_apply_post_checkout_status(room, status="dirty"):
    """Clear stay/merge and promote upcomingStay, or mark dirty."""
    upcoming = _hotel_upcoming_stay_dict(room)
    room.pop("stay", None)
    _hotel_clear_room_merge_fields(room)
    if upcoming:
        room["stay"] = _normalize_hotel_room_stay(upcoming)
        if not room["stay"].get("bookingNumber"):
            room["stay"]["bookingNumber"] = (
                f"BK{datetime.now().strftime('%Y%m%d%H%M%S')}"
            )
        room["status"] = "reserved"
        room.pop("upcomingStay", None)
        room.pop("upcoming_stay", None)
        return
    room.pop("upcomingStay", None)
    room.pop("upcoming_stay", None)
    room["status"] = _normalize_hotel_room_status(status)


def checkout_hotel_merge_group(conn, room_id, status="dirty"):
    """Check out every occupied room in this billing merge. Rooms become dirty.

    Snapshots invoices while stays still exist. Upcoming reservations are promoted
    per room. Not-in-a-group rooms fall through to a single checkout.
    The billing primary must already have a generated invoice.
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = _hotel_find_room(rooms, room_id)
    if not target:
        raise ValueError("Room not found.")

    group_id = _hotel_room_merge_group_id(target)
    billing_id = target.get("id") or room_id
    if group_id:
        billing = None
        for peer in _hotel_rooms_in_merge_group(rooms, group_id):
            stay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
            if stay and not (
                stay.get("mergeRole") == "member" or stay.get("billingRoomId")
            ):
                billing = peer
                break
        if billing is None:
            for peer in _hotel_rooms_in_merge_group(rooms, group_id):
                if peer.get("mergePrimary"):
                    billing = peer
                    break
        if billing is not None:
            billing_id = billing.get("id") or billing_id
    require_hotel_room_invoice_for_checkout(conn, billing_id)
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = _hotel_find_room(rooms, room_id)
    if not target:
        raise ValueError("Room not found.")
    group_id = _hotel_room_merge_group_id(target)
    if not group_id:
        stay = target.get("stay") if isinstance(target.get("stay"), dict) else None
        copied = dict(stay) if stay else None
        if stay:
            sync_pos_room_transfer_invoices_for_stay(conn, target)
        if stay and (stay.get("invoiceNumber") or stay.get("invoice_number")):
            upsert_hotel_room_invoice_from_room(conn, target)
        _hotel_apply_post_checkout_status(target, status=status)
        saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
        rid = str(target.get("id") or room_id)
        return {
            "room": get_hotel_room(conn, rid),
            "layout": saved,
            "checkedOutRoomIds": [rid],
            "checkedOutStays": [copied] if copied else [],
        }

    peers = list(_hotel_rooms_in_merge_group(rooms, group_id))
    to_checkout = []
    for peer in peers:
        if _normalize_hotel_room_status(peer.get("status")) == "occupied":
            to_checkout.append(peer)

    def _checkout_rank(room):
        primary = 0 if room.get("mergePrimary") else 1
        return (primary, str(room.get("number") or room.get("id") or ""))

    to_checkout.sort(key=_checkout_rank)

    checked_ids = []
    checked_stays = []
    for peer in to_checkout:
        stay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
        if stay:
            checked_stays.append(dict(stay))
            sync_pos_room_transfer_invoices_for_stay(conn, peer)
            if stay.get("invoiceNumber") or stay.get("invoice_number"):
                upsert_hotel_room_invoice_from_room(conn, peer)
        checked_ids.append(str(peer.get("id") or "").strip())
        _hotel_apply_post_checkout_status(peer, status=status)

    for peer in _hotel_rooms_in_merge_group(rooms, group_id):
        pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
        if pstay:
            pstay = dict(pstay)
            pstay["billingRoomId"] = ""
            pstay["mergeRole"] = ""
            peer["stay"] = pstay
        _hotel_clear_room_merge_fields(peer)

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    out = get_hotel_room(conn, room_id)
    if out:
        enrich_hotel_room_merge_fields(out, saved.get("rooms"))
    return {
        "room": out,
        "layout": saved,
        "checkedOutRoomIds": [rid for rid in checked_ids if rid],
        "checkedOutStays": checked_stays,
    }


def transfer_hotel_room_stay(conn, from_room_id, to_room_id, note=""):
    """Move an in-house stay to another vacant room.

    Source becomes dirty (cleared). Destination becomes occupied with the stay.
    Only vacant rooms are accepted as transfer targets.

    Merge-aware:
    - Member transfer keeps billingRoomId and remaps mergeGroupId onto the new room.
    - Primary transfer remaps mergePrimary and all members' billingRoomId.
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    from_id = str(from_room_id or "").strip()
    to_id = str(to_room_id or "").strip()
    if not from_id or not to_id:
        raise ValueError("Source and destination rooms are required.")
    if from_id == to_id:
        raise ValueError("Choose a different room to transfer to.")

    source = _hotel_find_room(rooms, from_id)
    destination = _hotel_find_room(rooms, to_id)

    if not source:
        raise ValueError("Source room not found.")
    if not destination:
        raise ValueError("Destination room not found.")

    source_status = _normalize_hotel_room_status(source.get("status"))
    stay = source.get("stay")
    if source_status != "occupied" or not isinstance(stay, dict) or not stay:
        raise ValueError("Only occupied rooms with a checked-in guest can be transferred.")

    dest_status = _normalize_hotel_room_status(destination.get("status"))
    if dest_status != "vacant":
        raise ValueError("Guest can only be transferred to a vacant room.")
    # Vacant rooms may still carry a cancelled reservation shell (dates, empty guest).
    # Clear that so transfer can proceed; only block a real in-house stay.
    if isinstance(destination.get("stay"), dict) and destination.get("stay"):
        if _hotel_room_has_inhouse_stay(destination):
            raise ValueError("Destination room already has guest details.")
        destination.pop("stay", None)

    moved = _normalize_hotel_room_stay(dict(stay))
    note_text = _hotel_str(note, 400)
    if note_text:
        existing = moved.get("notes") or ""
        moved["notes"] = (
            (existing + " | " if existing else "") + "Transfer: " + note_text
        )[:500]
    history = moved.get("transferHistory")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "fromRoomId": source.get("id"),
            "fromRoomNumber": source.get("number"),
            "toRoomId": destination.get("id"),
            "toRoomNumber": destination.get("number"),
            "at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "note": note_text,
        }
    )
    moved["transferHistory"] = history[-20:]
    moved["transferCount"] = len(moved["transferHistory"])

    group_id = _hotel_room_merge_group_id(source)
    was_primary = bool(source.get("mergePrimary") and moved.get("mergeRole") != "member")
    was_member = bool(moved.get("mergeRole") == "member" or moved.get("billingRoomId"))

    if was_primary and group_id:
        # Remap members to the new primary room id.
        for peer in _hotel_rooms_in_merge_group(rooms, group_id):
            if peer.get("id") == source.get("id"):
                continue
            pstay = peer.get("stay") if isinstance(peer.get("stay"), dict) else None
            if not pstay:
                continue
            pstay = dict(pstay)
            pstay["billingRoomId"] = destination.get("id")
            pstay["mergeRole"] = "member"
            peer["stay"] = _normalize_hotel_room_stay(pstay)
        destination["mergeGroupId"] = group_id
        destination["mergePrimary"] = True
        moved["mergeRole"] = "primary"
        moved["billingRoomId"] = ""
    elif was_member and group_id:
        destination["mergeGroupId"] = group_id
        destination["mergePrimary"] = False
        # billingRoomId already on stay
    else:
        _hotel_clear_room_merge_fields(destination)

    destination["stay"] = moved
    destination["status"] = "occupied"
    if moved.get("invoiceNumber"):
        upsert_hotel_room_invoice_from_room(conn, destination)

    source.pop("stay", None)
    _hotel_clear_room_merge_fields(source)
    source["status"] = "dirty"

    saved = save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)
    from_room = None
    to_room = None
    for room in saved.get("rooms") or []:
        if room.get("id") == source.get("id"):
            from_room = room
        if room.get("id") == destination.get("id"):
            to_room = room
    if not from_room or not to_room:
        raise ValueError("Transfer failed.")
    floors = {f.get("id"): f for f in (saved.get("floors") or []) if isinstance(f, dict)}
    for room in (from_room, to_room):
        floor = floors.get(room.get("floorId")) or {}
        room["floorName"] = floor.get("name") or room.get("floorId") or ""
        room["statusLabel"] = HOTEL_ROOM_STATUS_LABELS.get(
            room.get("status"), room.get("status")
        )
        enrich_hotel_room_merge_fields(room, saved.get("rooms"))
    return {"fromRoom": from_room, "toRoom": to_room}


def update_hotel_room_status(conn, room_id, status, extras=None):
    """Update one room's status; returns normalized layout.

    For reserved, optional extras may include checkInDate / checkOutDate / asOf
    so the reservation covers the night the operator is viewing.

    Occupied → Dirty is allowed: it checks the guest out and leaves the room Dirty
    (same end state as checkout). Vacant while checked-in remains blocked.
    """
    layout = get_hotel_rooms_layout(conn)
    rooms = layout.get("rooms") or []
    target = str(room_id or "").strip()
    next_status = _normalize_hotel_room_status(status)
    extras = extras if isinstance(extras, dict) else {}
    found = False
    for room in rooms:
        if room.get("id") == target or room.get("number") == target:
            prev_status = _normalize_hotel_room_status(room.get("status"))
            in_house = prev_status == "occupied" or _hotel_room_has_inhouse_stay(room)
            # Dirty while occupied = force checkout + dirty housekeeping.
            if next_status == "dirty" and in_house:
                return clear_hotel_room_stay(conn, room_id, status="dirty")
            # Other status changes stay blocked until FO checkout clears the stay.
            if next_status != "occupied" and in_house:
                raise ValueError(
                    "Guest is still checked in. Check out the room before changing status."
                )
            room["status"] = next_status
            if next_status == "reserved":
                check_in = _hotel_str(
                    extras.get("checkInDate")
                    or extras.get("check_in_date")
                    or extras.get("asOf")
                    or extras.get("as_of"),
                    20,
                )[:10]
                check_out = _hotel_str(
                    extras.get("checkOutDate") or extras.get("check_out_date"),
                    20,
                )[:10]
                if check_in and len(check_in) >= 10:
                    check_in = check_in[:10]
                    if not check_out or len(check_out) < 10:
                        try:
                            base = datetime.strptime(check_in, "%Y-%m-%d")
                            check_out = (base + timedelta(days=1)).strftime("%Y-%m-%d")
                        except ValueError:
                            check_out = ""
                    else:
                        check_out = check_out[:10]
                    stay = room.get("stay") if isinstance(room.get("stay"), dict) else {}
                    stay = dict(stay)
                    stay["checkInDate"] = check_in
                    if check_out:
                        stay["checkOutDate"] = check_out
                    guest_name = _hotel_str(
                        extras.get("guestName") or extras.get("guest_name"), 160
                    )
                    first_name = _hotel_str(
                        extras.get("firstName") or extras.get("first_name"), 80
                    )
                    last_name = _hotel_str(
                        extras.get("lastName") or extras.get("last_name"), 80
                    )
                    if guest_name:
                        stay["guestName"] = guest_name
                        if first_name or last_name:
                            stay["firstName"] = first_name
                            stay["lastName"] = last_name
                        elif not (stay.get("firstName") or stay.get("lastName")):
                            parts = guest_name.split()
                            stay["firstName"] = parts[0] if parts else ""
                            stay["lastName"] = " ".join(parts[1:]) if len(parts) > 1 else ""
                    try:
                        rate_val = float(stay.get("roomRate") or stay.get("room_rate") or 0)
                    except (TypeError, ValueError):
                        rate_val = 0.0
                    if rate_val <= 0:
                        stay["roomRate"] = _hotel_rate_for_room_type(
                            room.get("roomType") or room.get("room_type"),
                            get_hotel_tariff_rates(conn),
                        )
                    room["stay"] = _normalize_hotel_room_stay(stay)
            found = True
            break
    if not found:
        raise ValueError("Room not found.")
    return save_hotel_rooms_layout(conn, layout.get("floors") or [], rooms)


def get_hotel_room(conn, room_id):
    """Return one room dict plus floor name, or None."""
    layout = get_hotel_rooms_layout(conn)
    target = str(room_id or "").strip()
    if not target:
        return None
    floors = {f.get("id"): f for f in (layout.get("floors") or []) if isinstance(f, dict)}
    for room in layout.get("rooms") or []:
        if not isinstance(room, dict):
            continue
        if room.get("id") == target or room.get("number") == target:
            floor = floors.get(room.get("floorId")) or {}
            result = dict(room)
            result["floorName"] = floor.get("name") or room.get("floorId") or ""
            result["statusLabel"] = HOTEL_ROOM_STATUS_LABELS.get(
                result.get("status"), result.get("status")
            )
            enrich_hotel_room_merge_fields(result, layout.get("rooms"))
            stay = result.get("stay")
            if isinstance(stay, dict) and stay:
                enriched = _hotel_enrich_folio_transfer_tax(conn, stay)
                if enriched is not stay:
                    result = dict(result)
                    result["stay"] = enriched
            return result
    return None


APP_LICENSE_ROW_ID = 1
LICENSE_EXPIRING_SOON_DAYS = 30


def _license_parse_date(value):
    text = str(value or "").strip()[:10]
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def ensure_app_license_schema(conn):
    """Create app license + renewal history tables and seed a default active row."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_license (
            id            INTEGER PRIMARY KEY CHECK (id = 1),
            license_type  TEXT    NOT NULL DEFAULT 'Business Standard',
            license_key   TEXT    NOT NULL DEFAULT '',
            valid_from    TEXT    NOT NULL,
            valid_to      TEXT    NOT NULL,
            status        TEXT    NOT NULL DEFAULT 'active',
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_license_renewals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            valid_from  TEXT    NOT NULL,
            valid_to    TEXT    NOT NULL,
            note        TEXT    NOT NULL DEFAULT '',
            updated_by  TEXT    NOT NULL DEFAULT '',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_app_license_renewals_created
        ON app_license_renewals(id DESC)
        """
    )
    row = conn.execute(
        "SELECT id FROM app_license WHERE id = ?",
        (APP_LICENSE_ROW_ID,),
    ).fetchone()
    if row:
        return
    today = date.today()
    valid_from = today.isoformat()
    valid_to = (today + timedelta(days=365)).isoformat()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    key = f"HBE-STD-{today.year}-SEED-0001"
    conn.execute(
        """
        INSERT INTO app_license (
            id, license_type, license_key, valid_from, valid_to, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'active', ?, ?)
        """,
        (
            APP_LICENSE_ROW_ID,
            "Business Standard",
            key,
            valid_from,
            valid_to,
            now,
            now,
        ),
    )
    conn.execute(
        """
        INSERT INTO app_license_renewals (
            valid_from, valid_to, note, updated_by, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (valid_from, valid_to, "Initial license seed", "system", now),
    )


def _license_status_for_dates(valid_from, valid_to, when=None):
    """Return active | expiring_soon | expired from date window."""
    today = when if isinstance(when, date) else date.today()
    if isinstance(when, datetime):
        today = when.date()
    start = _license_parse_date(valid_from)
    end = _license_parse_date(valid_to)
    if end is None:
        return "expired"
    if start and today < start:
        return "expired"
    if today > end:
        return "expired"
    days = (end - today).days
    if days <= LICENSE_EXPIRING_SOON_DAYS:
        return "expiring_soon"
    return "active"


def license_days_remaining(conn, when=None):
    """Days until valid_to (0 if expired same day end; negative if past)."""
    ensure_app_license_schema(conn)
    row = conn.execute(
        "SELECT valid_to FROM app_license WHERE id = ?",
        (APP_LICENSE_ROW_ID,),
    ).fetchone()
    end = _license_parse_date(row["valid_to"] if row else None)
    if end is None:
        return None
    today = when if isinstance(when, date) else date.today()
    if isinstance(when, datetime):
        today = when.date()
    return (end - today).days


def license_is_active(conn, when=None):
    """True when today is within valid_from..valid_to inclusive."""
    ensure_app_license_schema(conn)
    row = conn.execute(
        "SELECT valid_from, valid_to FROM app_license WHERE id = ?",
        (APP_LICENSE_ROW_ID,),
    ).fetchone()
    if not row:
        return False
    return _license_status_for_dates(row["valid_from"], row["valid_to"], when) != "expired"


def get_app_license(conn):
    """Current license row as a dict (creates schema/seed if needed)."""
    ensure_app_license_schema(conn)
    row = conn.execute(
        """
        SELECT id, license_type, license_key, valid_from, valid_to, status,
               created_at, updated_at
        FROM app_license
        WHERE id = ?
        """,
        (APP_LICENSE_ROW_ID,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    status = _license_status_for_dates(data.get("valid_from"), data.get("valid_to"))
    data["status"] = status
    days = license_days_remaining(conn)
    data["days_remaining"] = days
    return data


def list_license_renewals(conn, limit=50):
    """Newest-first renewal history rows."""
    ensure_app_license_schema(conn)
    lim = max(1, min(int(limit or 50), 200))
    rows = conn.execute(
        """
        SELECT id, valid_from, valid_to, note, updated_by, created_at
        FROM app_license_renewals
        ORDER BY id DESC
        LIMIT ?
        """,
        (lim,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_app_license(
    conn,
    *,
    valid_to,
    valid_from=None,
    license_type=None,
    license_key=None,
    note="",
    updated_by="",
):
    """Update the current license window and append a renewal history row."""
    ensure_app_license_schema(conn)
    current = get_app_license(conn)
    if not current:
        raise ValueError("License record is missing.")
    end = _license_parse_date(valid_to)
    if end is None:
        raise ValueError("valid_to must be YYYY-MM-DD.")
    start = _license_parse_date(valid_from) if valid_from is not None else _license_parse_date(
        current.get("valid_from")
    )
    if start is None:
        start = date.today()
    if end < start:
        raise ValueError("valid_to must be on or after valid_from.")
    typ = str(license_type if license_type is not None else current.get("license_type") or "").strip()
    if not typ:
        typ = "Business Standard"
    key = str(license_key if license_key is not None else current.get("license_key") or "").strip()
    if not key:
        key = f"HBE-STD-{start.year}-SEED-0001"
    status = _license_status_for_dates(start.isoformat(), end.isoformat())
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE app_license
        SET license_type = ?, license_key = ?, valid_from = ?, valid_to = ?,
            status = ?, updated_at = ?
        WHERE id = ?
        """,
        (typ, key, start.isoformat(), end.isoformat(), status, now, APP_LICENSE_ROW_ID),
    )
    conn.execute(
        """
        INSERT INTO app_license_renewals (
            valid_from, valid_to, note, updated_by, created_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            start.isoformat(),
            end.isoformat(),
            str(note or "").strip(),
            str(updated_by or "").strip(),
            now,
        ),
    )
    return get_app_license(conn)


def init_db():
    conn = get_db()
    conn.execute("PRAGMA journal_mode=WAL")
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            username        TEXT    NOT NULL UNIQUE,
            full_name       TEXT    NOT NULL DEFAULT '',
            password_hash   TEXT    NOT NULL,
            is_admin        INTEGER NOT NULL DEFAULT 0,
            is_active       INTEGER NOT NULL DEFAULT 1,
            email           TEXT    NOT NULL DEFAULT '',
            failed_login_attempts INTEGER NOT NULL DEFAULT 0,
            captcha_required INTEGER NOT NULL DEFAULT 0,
            locked_at       TEXT,
            unlock_token_hash TEXT,
            unlock_token_expires_at TEXT,
            created_at      TEXT    NOT NULL,
            updated_at      TEXT    NOT NULL
        )
    """)
    existing_user_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(users)").fetchall()
    }
    if "email" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN email TEXT NOT NULL DEFAULT ''")
    if "failed_login_attempts" not in existing_user_cols:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN failed_login_attempts INTEGER NOT NULL DEFAULT 0"
        )
    if "captcha_required" not in existing_user_cols:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN captcha_required INTEGER NOT NULL DEFAULT 0"
        )
    if "locked_at" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN locked_at TEXT")
    if "unlock_token_hash" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN unlock_token_hash TEXT")
    if "unlock_token_expires_at" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN unlock_token_expires_at TEXT")
    if "role_id" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN role_id INTEGER")
    if "photo_path" not in existing_user_cols:
        cursor.execute("ALTER TABLE users ADD COLUMN photo_path TEXT NOT NULL DEFAULT ''")
    if "must_change_password" not in existing_user_cols:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN must_change_password INTEGER NOT NULL DEFAULT 0"
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS login_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  TEXT    NOT NULL,
            username    TEXT    NOT NULL DEFAULT '',
            user_id     INTEGER,
            success     INTEGER NOT NULL DEFAULT 0,
            reason      TEXT    NOT NULL DEFAULT '',
            ip_address  TEXT    NOT NULL DEFAULT '',
            user_agent  TEXT    NOT NULL DEFAULT ''
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_login_logs_created ON login_logs(id DESC)"
    )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_permissions (
            user_id  INTEGER NOT NULL,
            scope    TEXT    NOT NULL,
            item_key TEXT    NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_roles (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            description TEXT    NOT NULL DEFAULT '',
            is_admin    INTEGER NOT NULL DEFAULT 0,
            is_active   INTEGER NOT NULL DEFAULT 1,
            created_at  TEXT    NOT NULL,
            updated_at  TEXT    NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_role_permissions (
            role_id  INTEGER NOT NULL,
            scope    TEXT    NOT NULL,
            item_key TEXT    NOT NULL,
            UNIQUE(role_id, scope, item_key)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_updates (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            company                 TEXT    NOT NULL,
            location                TEXT    NOT NULL,
            sales_date              TEXT    NOT NULL,
            sales_entry_values      TEXT    NOT NULL DEFAULT '{}',
            sales_entry_total       REAL    NOT NULL DEFAULT 0,
            petty_cash_counts       TEXT    NOT NULL DEFAULT '{}',
            petty_cash_total        REAL    NOT NULL DEFAULT 0,
            cash_denomination_counts TEXT   NOT NULL DEFAULT '{}',
            created_by_user_id      INTEGER,
            updated_by_user_id      INTEGER,
            created_at              TEXT    NOT NULL,
            updated_at              TEXT    NOT NULL,
            UNIQUE(company, location, sales_date)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_expenses (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
            description     TEXT    NOT NULL DEFAULT '',
            amount          REAL    NOT NULL DEFAULT 0,
            payment_type    TEXT    NOT NULL DEFAULT 'cash',
            transaction_id  TEXT    NOT NULL DEFAULT '',
            expense_code    TEXT    NOT NULL DEFAULT '',
            entry_kind      TEXT    NOT NULL DEFAULT 'expense',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    existing_expense_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(sales_update_expenses)").fetchall()
    }
    if "payment_type" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN payment_type TEXT NOT NULL DEFAULT 'cash'")
    if "transaction_id" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN transaction_id TEXT NOT NULL DEFAULT ''")
    if "supplier_id" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN supplier_id INTEGER")
    if "category" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN category TEXT NOT NULL DEFAULT ''")
    if "expense_code" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN expense_code TEXT NOT NULL DEFAULT ''")
        rows = cursor.execute(
            """SELECT id, company FROM sales_update_expenses
               WHERE expense_code IS NULL OR expense_code = ''
               ORDER BY id"""
        ).fetchall()
        company_counters = {}
        for row in rows:
            company = (row["company"] or "HBE").strip() or "HBE"
            company_counters[company] = company_counters.get(company, 0) + 1
            code = f"{company}-EX-{company_counters[company]}"
            cursor.execute(
                "UPDATE sales_update_expenses SET expense_code = ? WHERE id = ?",
                (code, row["id"]),
            )
    if "invoice_number" not in existing_expense_cols:
        cursor.execute("ALTER TABLE sales_update_expenses ADD COLUMN invoice_number TEXT NOT NULL DEFAULT ''")
    if "entry_kind" not in existing_expense_cols:
        # Historical rows were treated as expenses; new purchases opt in explicitly.
        cursor.execute(
            "ALTER TABLE sales_update_expenses ADD COLUMN entry_kind TEXT NOT NULL DEFAULT 'expense'"
        )
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_expenses_kind
        ON sales_update_expenses(location, entry_kind, sales_date)
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sales_update_expenses_code
        ON sales_update_expenses(expense_code)
        WHERE expense_code != ''
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS expense_categories (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            category_key  TEXT    NOT NULL UNIQUE,
            name          TEXT    NOT NULL COLLATE NOCASE,
            sort_order    INTEGER NOT NULL DEFAULT 0,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_expense_categories_name
        ON expense_categories(lower(name))
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS suppliers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT    NOT NULL,
            gst                 TEXT    NOT NULL DEFAULT '',
            address             TEXT    NOT NULL DEFAULT '',
            phone               TEXT    NOT NULL DEFAULT '',
            bank_name           TEXT    NOT NULL DEFAULT '',
            bank_account_number TEXT    NOT NULL DEFAULT '',
            ifsc_code           TEXT    NOT NULL DEFAULT '',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    _migrate_suppliers_optional_gst(cursor)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_suppliers_name
        ON suppliers(LOWER(name))
    """)
    cursor.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_suppliers_gst_unique
        ON suppliers(gst) WHERE gst != ''
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_cash_transfers (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            company     TEXT    NOT NULL,
            location    TEXT    NOT NULL,
            sales_date  TEXT    NOT NULL,
            destination TEXT    NOT NULL DEFAULT 'bank',
            description TEXT    NOT NULL DEFAULT '',
            amount      REAL    NOT NULL DEFAULT 0,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_pending_bills (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            company              TEXT    NOT NULL,
            location             TEXT    NOT NULL,
            recorded_sales_date  TEXT    NOT NULL,
            invoice_number       TEXT    NOT NULL DEFAULT '',
            amount               REAL    NOT NULL DEFAULT 0,
            status               TEXT    NOT NULL DEFAULT 'open',
            cleared_sales_date   TEXT,
            created_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at           TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_bill_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
            pending_bill_id INTEGER NOT NULL,
            amount          REAL    NOT NULL DEFAULT 0,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_updates_scope_date
        ON sales_updates(company, location, sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_expenses_scope
        ON sales_update_expenses(company, location, sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_cash_transfers_scope
        ON sales_update_cash_transfers(company, location, sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_pending_bills_scope
        ON sales_update_pending_bills(company, location, status, recorded_sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_bill_payments_scope
        ON sales_update_bill_payments(company, location, sales_date)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credit_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            supplier_id     INTEGER NOT NULL,
            payment_date    TEXT    NOT NULL,
            payment_method  TEXT    NOT NULL DEFAULT 'cash',
            transaction_id  TEXT    NOT NULL DEFAULT '',
            total_amount    REAL    NOT NULL DEFAULT 0,
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credit_payment_allocations (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            credit_payment_id   INTEGER NOT NULL,
            expense_id          INTEGER NOT NULL,
            amount              REAL    NOT NULL DEFAULT 0,
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_credit_payments_scope
        ON credit_payments(company, supplier_id, payment_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_credit_payment_allocations_payment
        ON credit_payment_allocations(credit_payment_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_credit_payment_allocations_expense
        ON credit_payment_allocations(expense_id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_verifications (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            company             TEXT    NOT NULL,
            supplier_id         INTEGER NOT NULL,
            verification_date   TEXT    NOT NULL,
            verification_method TEXT    NOT NULL DEFAULT 'cash',
            verification_account TEXT   NOT NULL DEFAULT '',
            transaction_id      TEXT    NOT NULL DEFAULT '',
            total_amount        REAL    NOT NULL DEFAULT 0,
            notes               TEXT    NOT NULL DEFAULT '',
            created_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at          TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS purchase_verification_allocations (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            purchase_verification_id INTEGER NOT NULL,
            expense_id              INTEGER NOT NULL,
            amount                  REAL    NOT NULL DEFAULT 0,
            created_at              TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchase_verifications_scope
        ON purchase_verifications(company, supplier_id, verification_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchase_verification_allocations_verification
        ON purchase_verification_allocations(purchase_verification_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_purchase_verification_allocations_expense
        ON purchase_verification_allocations(expense_id)
    """)
    ensure_cash_ledger_schema(conn)
    ensure_back_office_receipt_schema(conn)
    ensure_stores_schema(conn)
    ensure_pos_schema(conn)

    existing_pv_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(purchase_verifications)").fetchall()
    }
    if "verification_account" not in existing_pv_cols:
        cursor.execute(
            "ALTER TABLE purchase_verifications ADD COLUMN verification_account TEXT NOT NULL DEFAULT ''"
        )

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hotel_sales_ledger_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
            invoice_number  TEXT    NOT NULL DEFAULT '',
            room            TEXT    NOT NULL DEFAULT '',
            room_type       TEXT    NOT NULL DEFAULT '',
            reserve_number  TEXT    NOT NULL DEFAULT '',
            guest_name      TEXT    NOT NULL DEFAULT '',
            company_name    TEXT    NOT NULL DEFAULT '',
            travel_agent    TEXT    NOT NULL DEFAULT '',
            pax             TEXT    NOT NULL DEFAULT '',
            room_plan       TEXT    NOT NULL DEFAULT '',
            tariff          REAL    NOT NULL DEFAULT 0,
            discount        REAL    NOT NULL DEFAULT 0,
            extra_amount    REAL    NOT NULL DEFAULT 0,
            amount          REAL    NOT NULL DEFAULT 0,
            payment_mode    TEXT    NOT NULL DEFAULT '',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            source_row      INTEGER,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_hotel_sales_ledger_scope
        ON hotel_sales_ledger_entries(company, location, sales_date, sort_order)
    """)
    existing_hotel_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(hotel_sales_ledger_entries)").fetchall()
    }
    if "invoice_number" not in existing_hotel_cols:
        cursor.execute("ALTER TABLE hotel_sales_ledger_entries ADD COLUMN invoice_number TEXT NOT NULL DEFAULT ''")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS room_transfer_entries (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            location        TEXT    NOT NULL,
            sales_date      TEXT    NOT NULL,
            invoice_number  TEXT    NOT NULL DEFAULT '',
            outlet_name     TEXT    NOT NULL DEFAULT '',
            table_room      TEXT    NOT NULL DEFAULT '',
            guest_name      TEXT    NOT NULL DEFAULT '',
            ledger_detail   TEXT    NOT NULL DEFAULT '',
            amount          REAL    NOT NULL DEFAULT 0,
            payment_status  TEXT    NOT NULL DEFAULT 'unpaid',
            sort_order      INTEGER NOT NULL DEFAULT 0,
            source_row      INTEGER,
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_transfer_scope
        ON room_transfer_entries(company, sales_date, location, sort_order)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS room_transfer_payments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            company         TEXT    NOT NULL,
            payment_date    TEXT    NOT NULL,
            payment_method  TEXT    NOT NULL DEFAULT 'cash',
            transaction_id  TEXT    NOT NULL DEFAULT '',
            total_amount    REAL    NOT NULL DEFAULT 0,
            notes           TEXT    NOT NULL DEFAULT '',
            created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS room_transfer_payment_allocations (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            room_transfer_payment_id INTEGER NOT NULL,
            room_transfer_entry_id   INTEGER NOT NULL,
            amount                   REAL    NOT NULL DEFAULT 0,
            invoice_number           TEXT    NOT NULL DEFAULT '',
            guest_name               TEXT    NOT NULL DEFAULT '',
            location                 TEXT    NOT NULL DEFAULT '',
            sales_date               TEXT    NOT NULL DEFAULT '',
            created_at               TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_transfer_payments_scope
        ON room_transfer_payments(company, payment_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_transfer_payment_allocations_payment
        ON room_transfer_payment_allocations(room_transfer_payment_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_room_transfer_payment_allocations_entry
        ON room_transfer_payment_allocations(room_transfer_entry_id)
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS employees (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            emp_code     TEXT    NOT NULL DEFAULT '',
            name         TEXT    NOT NULL,
            company      TEXT    NOT NULL DEFAULT '',
            location     TEXT    NOT NULL DEFAULT '',
            mobile           TEXT    NOT NULL DEFAULT '',
            guardian_mobile  TEXT    NOT NULL DEFAULT '',
            sex          TEXT    NOT NULL DEFAULT '',
            address      TEXT    NOT NULL DEFAULT '',
            aadhar       TEXT    NOT NULL DEFAULT '',
            pan          TEXT    NOT NULL DEFAULT '',
            epf_number   TEXT    NOT NULL DEFAULT '',
            esic_number  TEXT    NOT NULL DEFAULT '',
            gross_salary REAL    NOT NULL DEFAULT 0,
            basic_salary REAL    NOT NULL DEFAULT 0,
            epf_amount   REAL    NOT NULL DEFAULT 0,
            esic_amount  REAL    NOT NULL DEFAULT 0,
            credit_repayment REAL    NOT NULL DEFAULT 0,
            epf_exempt   INTEGER NOT NULL DEFAULT 0,
            esic_exempt  INTEGER NOT NULL DEFAULT 0,
            weekday_shift TEXT    NOT NULL DEFAULT '',
            sunday_shift  TEXT    NOT NULL DEFAULT '',
            bank_name         TEXT    NOT NULL DEFAULT '',
            account_holder_name TEXT  NOT NULL DEFAULT '',
            account_number    TEXT    NOT NULL DEFAULT '',
            ifsc_code         TEXT    NOT NULL DEFAULT '',
            total_off         INTEGER NOT NULL DEFAULT 0,
            status       TEXT    NOT NULL DEFAULT 'active',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            status      TEXT    NOT NULL DEFAULT 'present',
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE,
            UNIQUE(employee_id, date)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS credits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            employee_id INTEGER NOT NULL,
            date        TEXT    NOT NULL,
            description TEXT    NOT NULL DEFAULT '',
            amount      REAL    NOT NULL DEFAULT 0,
            entry_type  TEXT    NOT NULL DEFAULT 'manual',
            payroll_year INTEGER,
            payroll_month INTEGER,
            expense_id  INTEGER,
            created_at  TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )
    """)
    existing_credit_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(credits)").fetchall()
    }
    if "expense_id" not in existing_credit_cols:
        cursor.execute("ALTER TABLE credits ADD COLUMN expense_id INTEGER")
    if "sales_company" not in existing_credit_cols:
        cursor.execute("ALTER TABLE credits ADD COLUMN sales_company TEXT")
    if "sales_location" not in existing_credit_cols:
        cursor.execute("ALTER TABLE credits ADD COLUMN sales_location TEXT")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sales_update_tips (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            company      TEXT    NOT NULL,
            location     TEXT    NOT NULL,
            sales_date   TEXT    NOT NULL,
            employee_id  INTEGER NOT NULL,
            amount       REAL    NOT NULL DEFAULT 0,
            description  TEXT    NOT NULL DEFAULT '',
            created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_tips_scope
        ON sales_update_tips(company, location, sales_date)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sales_update_tips_employee
        ON sales_update_tips(employee_id, sales_date)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tip_incentive_payouts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            company      TEXT    NOT NULL,
            year         INTEGER NOT NULL,
            month        INTEGER NOT NULL,
            employee_id  INTEGER NOT NULL,
            amount       REAL    NOT NULL DEFAULT 0,
            updated_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
            UNIQUE(company, year, month, employee_id),
            FOREIGN KEY (employee_id) REFERENCES employees(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tip_incentive_payouts_period
        ON tip_incentive_payouts(company, year, month)
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payroll_month_locks (
            year      INTEGER NOT NULL,
            month     INTEGER NOT NULL,
            locked_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            PRIMARY KEY (year, month)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payroll_month_employee_off (
            year         INTEGER NOT NULL,
            month        INTEGER NOT NULL,
            employee_id  INTEGER NOT NULL,
            total_off    INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (year, month, employee_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payroll_month_employee_wages (
            year          INTEGER NOT NULL,
            month         INTEGER NOT NULL,
            employee_id   INTEGER NOT NULL,
            gross_salary  REAL,
            basic_salary  REAL,
            epf_amount    REAL,
            esic_amount   REAL,
            epf_exempt    INTEGER,
            esic_exempt   INTEGER,
            total_off     INTEGER,
            PRIMARY KEY (year, month, employee_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS companies (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS locations (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_att_emp_date ON attendance(employee_id, date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_credits_emp ON credits(employee_id)")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_credits_emp_period "
        "ON credits(employee_id, entry_type, payroll_year, payroll_month)"
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_emp_status ON employees(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_emp_company ON employees(company)")
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_emp_code_unique "
        "ON employees(emp_code) WHERE emp_code <> ''"
    )
    existing_employee_cols = {
        row["name"] for row in cursor.execute("PRAGMA table_info(employees)").fetchall()
    }
    if "total_off" not in existing_employee_cols:
        cursor.execute("ALTER TABLE employees ADD COLUMN total_off INTEGER NOT NULL DEFAULT 0")
    for company_name in ("Hotel Bell Elite", "HBE"):
        cursor.execute(
            "INSERT OR IGNORE INTO companies (name) VALUES (?)",
            (company_name,),
        )
    payroll_departments = (
        "OM",
        "FO",
        "F&B",
        "KITCHEN",
        "UTILITY",
        "BAR",
        "HK",
        "MAINTENANCE",
        "SECURITY",
    )
    for location_name in payroll_departments:
        cursor.execute(
            "INSERT OR IGNORE INTO locations (name) VALUES (?)",
            (location_name,),
        )

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Seed only an empty users table. Do not recreate "admin" after it has been renamed.
    any_user = cursor.execute("SELECT id FROM users LIMIT 1").fetchone()
    if not any_user:
        cursor.execute(
            """INSERT INTO users (username, full_name, password_hash, is_admin, is_active, created_at, updated_at)
               VALUES (?, ?, ?, 1, 1, ?, ?)""",
            ("admin", "Administrator", auth_security.hash_password("admin"), now, now),
        )

    from workspace_access import ensure_access_roles_schema

    ensure_access_roles_schema(conn)

    ensure_hotel_rooms_schema(conn)
    get_hotel_rooms_layout(conn)
    ensure_agencies_schema(conn)
    ensure_communication_hub_schema(conn)
    ensure_app_license_schema(conn)

    conn.commit()
    conn.close()
