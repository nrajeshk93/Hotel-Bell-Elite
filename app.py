"""Hotel Bell Elite — Sales Update application."""

import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import (
    Flask,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash

from db import SQL_NOW, get_db, init_db
from occupancy_summary_parser import parse_occupancy_summary_report
from sales_report_parser import OUTLET_BAR, OUTLET_RESTAURANT, parse_order_invoice_report

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "hotel-bell-elite-dev-key-change-in-production")

init_db()

AUTH_USER_SESSION_KEY = "user_id"

SALES_COMPANY_LOCATIONS = {
    "HBE": {
        "label": "Hotel Bell Elite",
        "locations": ["Bar", "Restaurant"],
    }
}

SALES_ENTRY_FIELDS = (
    ("total_sales", "Total Sales"),
    ("cash", "Cash"),
    ("card", "Card"),
    ("upi", "UPI"),
    ("room_credit", "Room Transfer"),
)

SALES_ENTRY_TOTAL_KEYS = (
    "cash",
    "card",
    "upi",
    "room_credit",
)

SALES_DIGITAL_TRANSACTION_KEYS = ("card", "upi")

PETTY_CASH_DENOMINATIONS = (500, 200, 100, 50, 20, 10, 5, 2, 1)

SALES_CASH_DESTINATIONS = {
    "bank": "Bank deposit",
    "petty_cash": "Petty cash",
    "other": "Other",
}

DEFAULT_COMPANY = "HBE"
DEFAULT_LOCATION = OUTLET_BAR
OUTLET_HOTEL = "Hotel"
HOTEL_LOCATIONS = [OUTLET_HOTEL]
HOTEL_PAYMENT_MODES = (
    ("", "Unassigned"),
    ("cash", "Cash"),
    ("card", "Card"),
    ("upi", "UPI"),
    ("room_credit", "Room Transfer"),
)

IMPORT_FIELD_KEYS = ("total_sales", "cash", "card", "upi", "room_credit")


def round_half_up(value, dec=0):
    try:
        quantum = Decimal("1").scaleb(-dec)
        return float(Decimal(str(value or 0)).quantize(quantum, rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def parse_money(value):
    try:
        return round_half_up(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def get_current_user():
    user_id = session.get(AUTH_USER_SESSION_KEY)
    if not user_id:
        return None
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def user_can_access_dashboard(user, module_key):
    if not user:
        return False
    if user.get("is_admin"):
        return True
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT item_key FROM user_permissions WHERE user_id = ? AND scope = ?",
            (user["id"], "dashboard"),
        ).fetchall()
        return module_key in {r["item_key"] for r in rows}
    finally:
        conn.close()


def get_sales_entry_total(entries):
    return round_half_up(
        sum(parse_money(entries.get(key)) for key in SALES_ENTRY_TOTAL_KEYS),
        2,
    )


def get_denomination_total(counts_dict):
    total = 0
    for denom_str, count in (counts_dict or {}).items():
        try:
            total += int(denom_str) * int(count or 0)
        except (TypeError, ValueError):
            continue
    return total


def get_digital_transactions(entries):
    return round_half_up(
        sum(parse_money(entries.get(key)) for key in SALES_DIGITAL_TRANSACTION_KEYS),
        2,
    )


def get_difference(entries):
    return round_half_up(parse_money(entries.get("total_sales")) - get_sales_entry_total(entries), 2)


def _ledger_entry_to_dict(row):
    item = dict(row)
    for key in ("tariff", "discount", "extra_amount", "amount"):
        item[key] = round_half_up(item.get(key), 2)
    item["payment_mode"] = item.get("payment_mode") or ""
    return item


def load_hotel_ledger_entries(conn, company, location, sales_date):
    rows = conn.execute(
        """SELECT id, room, room_type, reserve_number, guest_name, company_name,
                  travel_agent, pax, room_plan, tariff, discount, extra_amount, amount,
                  payment_mode, sort_order, source_row
           FROM hotel_sales_ledger_entries
           WHERE company = ? AND location = ? AND sales_date = ?
           ORDER BY sort_order, id""",
        (company, location, sales_date),
    ).fetchall()
    return [_ledger_entry_to_dict(r) for r in rows]


def rollup_hotel_ledger_entries(entries):
    totals = {key: 0.0 for key in IMPORT_FIELD_KEYS}
    totals["total_sales"] = 0.0
    for entry in entries or []:
        amount = parse_money(entry.get("amount"))
        totals["total_sales"] = round_half_up(totals["total_sales"] + amount, 2)
        mode = (entry.get("payment_mode") or "").strip()
        if mode in SALES_ENTRY_TOTAL_KEYS:
            totals[mode] = round_half_up(totals[mode] + amount, 2)
    return totals


def replace_hotel_ledger_entries(conn, company, location, sales_date, lines):
    conn.execute(
        "DELETE FROM hotel_sales_ledger_entries WHERE company = ? AND location = ? AND sales_date = ?",
        (company, location, sales_date),
    )
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for line in lines:
        conn.execute(
            """INSERT INTO hotel_sales_ledger_entries
               (company, location, sales_date, room, room_type, reserve_number, guest_name,
                company_name, travel_agent, pax, room_plan, tariff, discount, extra_amount,
                amount, payment_mode, sort_order, source_row, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                company,
                location,
                sales_date,
                line.get("room", ""),
                line.get("room_type", ""),
                line.get("reserve_number", ""),
                line.get("guest_name", ""),
                line.get("company_name", ""),
                line.get("travel_agent", ""),
                line.get("pax", ""),
                line.get("room_plan", ""),
                parse_money(line.get("tariff")),
                parse_money(line.get("discount")),
                parse_money(line.get("extra_amount")),
                parse_money(line.get("amount")),
                (line.get("payment_mode") or "").strip(),
                int(line.get("sort_order") or 0),
                line.get("source_row"),
                now,
                now,
            ),
        )


def sync_hotel_sales_from_ledger(conn, user, company, location, sales_date):
    entries = load_hotel_ledger_entries(conn, company, location, sales_date)
    sales_entries = rollup_hotel_ledger_entries(entries)
    sales_entries = build_sales_entry_values(conn, company, location, sales_date, sales_entries)
    existing_row = load_sales_row(company, location, sales_date)
    petty = (existing_row or {}).get("petty_cash_counts", {})
    cash_denoms = (existing_row or {}).get("cash_denomination_counts", {})
    upsert_sales_row(user, company, location, sales_date, sales_entries, petty, cash_denoms)
    return {
        "entries": entries,
        "sales_entries": sales_entries,
        "sales_entry_total": get_sales_entry_total(sales_entries),
        "difference": get_difference(sales_entries),
    }


def _sales_expense_total(conn, company, location, sales_date):
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM sales_update_expenses WHERE company=? AND location=? AND sales_date=?",
        (company, location, sales_date),
    ).fetchone()
    return round_half_up(row["total"] if row else 0, 2)


def _sales_expense_entries(conn, company, location, sales_date):
    rows = conn.execute(
        "SELECT id, description, amount FROM sales_update_expenses WHERE company=? AND location=? AND sales_date=? ORDER BY created_at, id",
        (company, location, sales_date),
    ).fetchall()
    return [dict(r) for r in rows]


def _sales_unpaid_bill_total(conn, company, location, sales_date):
    row = conn.execute(
        """SELECT COALESCE(SUM(amount), 0) AS total FROM sales_update_pending_bills
           WHERE company=? AND location=? AND recorded_sales_date=? AND status='open'""",
        (company, location, sales_date),
    ).fetchone()
    return round_half_up(row["total"] if row else 0, 2)


def _sales_bill_payment_total(conn, company, location, sales_date):
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM sales_update_bill_payments WHERE company=? AND location=? AND sales_date=?",
        (company, location, sales_date),
    ).fetchone()
    return round_half_up(row["total"] if row else 0, 2)


def _sales_unpaid_bill_entries(conn, company, location, sales_date):
    rows = conn.execute(
        """SELECT id, invoice_number, amount FROM sales_update_pending_bills
           WHERE company=? AND location=? AND recorded_sales_date=? AND status='open'
           ORDER BY created_at, id""",
        (company, location, sales_date),
    ).fetchall()
    return [dict(r) for r in rows]


def _sales_bill_payment_entries(conn, company, location, sales_date):
    rows = conn.execute(
        """SELECT bp.id, bp.pending_bill_id, bp.amount, pb.invoice_number
           FROM sales_update_bill_payments bp
           LEFT JOIN sales_update_pending_bills pb ON pb.id = bp.pending_bill_id
           WHERE bp.company=? AND bp.location=? AND bp.sales_date=?
           ORDER BY bp.created_at, bp.id""",
        (company, location, sales_date),
    ).fetchall()
    return [dict(r) for r in rows]


def _sales_open_pending_bills(conn, company, location):
    rows = conn.execute(
        """SELECT id, invoice_number, amount, recorded_sales_date
           FROM sales_update_pending_bills
           WHERE company=? AND location=? AND status='open'
           ORDER BY recorded_sales_date DESC, id DESC""",
        (company, location),
    ).fetchall()
    return [dict(r) for r in rows]


def _sales_cash_transfer_total(conn, company, location, sales_date):
    row = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM sales_update_cash_transfers WHERE company=? AND location=? AND sales_date=?",
        (company, location, sales_date),
    ).fetchone()
    return round_half_up(row["total"] if row else 0, 2)


def _sales_cash_transfer_entries(conn, company, location, sales_date):
    rows = conn.execute(
        "SELECT id, destination, description, amount FROM sales_update_cash_transfers WHERE company=? AND location=? AND sales_date=? ORDER BY created_at, id",
        (company, location, sales_date),
    ).fetchall()
    return [dict(r) for r in rows]


def build_sales_entry_values(conn, company, location, sales_date, submitted_values=None):
    values = dict(submitted_values or {})
    for key, _label in SALES_ENTRY_FIELDS:
        values.setdefault(key, 0.0)
        values[key] = parse_money(values.get(key))
    return values


def load_sales_row(company, location, sales_date):
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM sales_updates WHERE company = ? AND location = ? AND sales_date = ?",
            (company, location, sales_date),
        ).fetchone()
        if not row:
            return None
        result = dict(row)
        result["sales_entry_values"] = json.loads(result.get("sales_entry_values") or "{}")
        result["petty_cash_counts"] = json.loads(result.get("petty_cash_counts") or "{}")
        result["cash_denomination_counts"] = json.loads(result.get("cash_denomination_counts") or "{}")
        return result
    finally:
        conn.close()


def upsert_sales_row(user, company, location, sales_date, sales_entries, petty_cash_counts=None, cash_denomination_counts=None):
    petty_cash_counts = petty_cash_counts or {}
    cash_denomination_counts = cash_denomination_counts or {}
    sales_entry_total = get_sales_entry_total(sales_entries)
    petty_cash_total = get_denomination_total(petty_cash_counts)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO sales_updates
               (company, location, sales_date, sales_entry_values, sales_entry_total,
                petty_cash_counts, petty_cash_total, cash_denomination_counts,
                created_by_user_id, updated_by_user_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(company, location, sales_date)
               DO UPDATE SET
                   sales_entry_values = excluded.sales_entry_values,
                   sales_entry_total = excluded.sales_entry_total,
                   petty_cash_counts = excluded.petty_cash_counts,
                   petty_cash_total = excluded.petty_cash_total,
                   cash_denomination_counts = excluded.cash_denomination_counts,
                   updated_by_user_id = excluded.updated_by_user_id,
                   updated_at = excluded.updated_at
            """,
            (
                company,
                location,
                sales_date,
                json.dumps(sales_entries),
                sales_entry_total,
                json.dumps(petty_cash_counts),
                petty_cash_total,
                json.dumps(cash_denomination_counts),
                user["id"],
                user["id"],
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "sales_entry_total": sales_entry_total,
        "petty_cash_total": petty_cash_total,
    }


def merge_import_into_sales_values(existing_values, imported_values):
    merged = dict(existing_values or {})
    for key in IMPORT_FIELD_KEYS:
        merged[key] = parse_money(imported_values.get(key))
    return merged


def _parse_sales_date(value):
    try:
        return date.fromisoformat((value or "").strip())
    except (TypeError, ValueError):
        return date.today()


def _pct_change_vs_previous(current, previous):
    try:
        cur = float(current or 0)
        prev = float(previous or 0)
    except (TypeError, ValueError):
        return None
    if prev == 0:
        if cur == 0:
            return 0.0
        return 100.0 if cur > 0 else -100.0
    return round((cur - prev) / abs(prev) * 100, 1)


def _aggregate_sales_kpis(conn, date_from, date_to, company=None, location=None):
    sql = "SELECT sales_entry_values FROM sales_updates WHERE sales_date >= ? AND sales_date <= ?"
    params = [date_from.isoformat(), date_to.isoformat()]
    if company:
        sql += " AND company = ?"
        params.append(company)
    if location:
        sql += " AND location = ?"
        params.append(location)
    rows = conn.execute(sql, params).fetchall()

    actual = digital = cash = difference = 0.0
    for row in rows:
        vals = json.loads(row["sales_entry_values"] or "{}")
        actual += parse_money(vals.get("total_sales"))
        digital += get_digital_transactions(vals)
        cash += parse_money(vals.get("cash"))
        difference += get_difference(vals)

    expense_sql = "SELECT COALESCE(SUM(amount), 0) AS total FROM sales_update_expenses WHERE sales_date >= ? AND sales_date <= ?"
    expense_params = [date_from.isoformat(), date_to.isoformat()]
    if company:
        expense_sql += " AND company = ?"
        expense_params.append(company)
    if location:
        expense_sql += " AND location = ?"
        expense_params.append(location)
    expense_row = conn.execute(expense_sql, expense_params).fetchone()
    expense = round_half_up(expense_row["total"] if expense_row else 0, 2)

    return {
        "actual_sales": round_half_up(actual, 2),
        "digital_transactions": round_half_up(digital, 2),
        "cash": round_half_up(cash, 2),
        "expense": expense,
        "difference": round_half_up(difference, 2),
    }


def _sales_report_kpi_bundle(conn, date_from, date_to, company=None, location=None):
    current = _aggregate_sales_kpis(conn, date_from, date_to, company, location)
    if date_from == date_to:
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to
        vs_label = "yesterday"
    else:
        span_days = (date_to - date_from).days + 1
        prev_to = date_from - timedelta(days=1)
        prev_from = prev_to - timedelta(days=span_days - 1)
        vs_label = "previous period"
    previous = _aggregate_sales_kpis(conn, prev_from, prev_to, company, location)
    trends = {
        key: _pct_change_vs_previous(current[key], previous[key])
        for key in ("actual_sales", "digital_transactions", "cash", "expense", "difference")
    }
    return {
        "current": current,
        "trends": trends,
        "vs_label": vs_label,
        "is_single_day": date_from == date_to,
    }


def _check_sales_date_lock(user, company, location, sales_date):
    today_iso = date.today().isoformat()
    if sales_date > today_iso:
        return "Cannot save future dates."
    if not user.get("is_admin") and sales_date < today_iso:
        if load_sales_row(company, location, sales_date):
            return "This date was already saved. Only administrators can change past sales entries."
    return None


@app.before_request
def require_login():
    public = {"index", "login", "static"}
    if not request.endpoint or request.endpoint in public:
        return None
    if get_current_user() is None:
        return redirect(url_for("index"))


@app.context_processor
def inject_auth_context():
    user = get_current_user()
    return {
        "current_user": user,
        "user_can_access_dashboard": user_can_access_dashboard,
    }


@app.template_filter("inr")
def inr_format(value, dec=0):
    try:
        v = float(value or 0)
        neg = v < 0
        v = abs(v)
        if dec <= 0:
            s = f"{int(round(v)):,}"
        else:
            s = f"{v:,.{dec}f}"
        parts = s.split(".")
        int_part = parts[0]
        if len(int_part) > 4:
            raw = int_part.replace(",", "")
            if len(raw) > 3:
                last3 = raw[-3:]
                rest = raw[:-3]
                groups = []
                while len(rest) > 2:
                    groups.insert(0, rest[-2:])
                    rest = rest[:-2]
                if rest:
                    groups.insert(0, rest)
                int_part = ",".join(groups) + "," + last3
        s = int_part + ("." + parts[1] if len(parts) > 1 else "")
        return ("−" if neg else "") + "₹" + s
    except (TypeError, ValueError):
        return "₹0"


@app.route("/")
def index():
    if get_current_user():
        return redirect(url_for("dashboard"))
    return render_template("index.html")


@app.route("/login", methods=["POST"])
def login():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", (username,)).fetchone()
    finally:
        conn.close()
    if not row or not check_password_hash(row["password_hash"], password):
        return render_template("index.html", error="Invalid username or password.")
    session[AUTH_USER_SESSION_KEY] = row["id"]
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.pop(AUTH_USER_SESSION_KEY, None)
    return redirect(url_for("index"))


@app.route("/dashboard")
def dashboard():
    today = date.today()
    conn = get_db()
    try:
        kpi_bundle = _sales_report_kpi_bundle(conn, today, today, DEFAULT_COMPANY, None)
    finally:
        conn.close()
    return render_template(
        "dashboard.html",
        current_user=get_current_user(),
        de_nav_section="analytics",
        de_nav_sales_view="dashboard",
        kpi=kpi_bundle["current"],
        kpi_trends=kpi_bundle["trends"],
        kpi_vs_label=kpi_bundle["vs_label"],
        selected_date=today.isoformat(),
    )


@app.route("/sales_update/hotel")
def sales_update_hotel():
    user = get_current_user()
    selected_company = request.args.get("company", DEFAULT_COMPANY)
    selected_location = request.args.get("location", OUTLET_HOTEL)
    selected_date = request.args.get("date", date.today().isoformat())
    today_iso = date.today().isoformat()

    if selected_company not in SALES_COMPANY_LOCATIONS:
        selected_company = DEFAULT_COMPANY
    if selected_location not in HOTEL_LOCATIONS:
        selected_location = OUTLET_HOTEL

    conn = get_db()
    try:
        entry_date = _parse_sales_date(selected_date)
        outlet_records = {
            OUTLET_HOTEL: _load_outlet_entry_bundle(
                conn, user, selected_company, OUTLET_HOTEL, selected_date, today_iso
            )
        }
        kpi_bundle = _sales_report_kpi_bundle(conn, entry_date, entry_date, selected_company, selected_location)
        ledger_entries = load_hotel_ledger_entries(conn, selected_company, selected_location, selected_date)
        ledger_rollup = rollup_hotel_ledger_entries(ledger_entries)
    finally:
        conn.close()

    hotel_outlet = outlet_records[OUTLET_HOTEL]
    return render_template(
        "sales_update_hotel.html",
        selected_company=selected_company,
        selected_company_label=SALES_COMPANY_LOCATIONS[selected_company]["label"],
        selected_location=selected_location,
        selected_locations=HOTEL_LOCATIONS,
        selected_date=selected_date,
        max_sales_date=today_iso,
        sales_company_locations=SALES_COMPANY_LOCATIONS,
        petty_cash_denominations=PETTY_CASH_DENOMINATIONS,
        outlet_records=outlet_records,
        sales_entry_locked=hotel_outlet["sales_entry_locked"],
        sales_update_is_admin=user.get("is_admin", False),
        hotel_payment_modes=HOTEL_PAYMENT_MODES,
        ledger_entries=ledger_entries,
        ledger_rollup=ledger_rollup,
        cash_date_from=selected_date,
        cash_date_to=selected_date,
        cash_panel=False,
        kpi=kpi_bundle["current"],
        kpi_trends=kpi_bundle["trends"],
        kpi_vs_label=kpi_bundle["vs_label"],
        de_nav_section="analytics",
        de_nav_sales_view="hotel",
    )


@app.route("/sales_update/hotel/upload_report", methods=["POST"])
def upload_hotel_occupancy_report():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    company = request.form.get("company", DEFAULT_COMPANY)
    location = request.form.get("location", OUTLET_HOTEL)
    sales_date_str = (request.form.get("date") or date.today().isoformat()).strip()
    if location not in HOTEL_LOCATIONS:
        location = OUTLET_HOTEL

    lock_error = _check_sales_date_lock(user, company, location, sales_date_str)
    if lock_error:
        return jsonify({"ok": False, "error": lock_error}), 403

    upload = request.files.get("report_file")
    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "Please choose an occupancy summary file."}), 400

    try:
        parsed = parse_occupancy_summary_report(upload.stream)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Could not read report: {exc}"}), 400

    if not parsed.get("lines"):
        return jsonify({"ok": False, "error": "No room lines found in the report."}), 400

    conn = get_db()
    try:
        replace_hotel_ledger_entries(conn, company, location, sales_date_str, parsed["lines"])
        conn.commit()
        result = sync_hotel_sales_from_ledger(conn, user, company, location, sales_date_str)
    finally:
        conn.close()

    meta = parsed.get("meta", {})
    return jsonify({
        "ok": True,
        "date": sales_date_str,
        "message": f"Imported {meta.get('line_count', 0)} room lines for {sales_date_str}",
        "ledger_entries": result["entries"],
        "sales_entries": result["sales_entries"],
        "ledger_rollup": rollup_hotel_ledger_entries(result["entries"]),
        "meta": meta,
    })


@app.route("/sales_update/hotel/save_ledger", methods=["POST"])
def save_hotel_ledger():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", OUTLET_HOTEL)
    sales_date = data.get("date", date.today().isoformat())
    updates = data.get("updates") or []

    if location not in HOTEL_LOCATIONS:
        location = OUTLET_HOTEL

    lock_error = _check_sales_date_lock(user, company, location, sales_date)
    if lock_error:
        return jsonify({"ok": False, "error": lock_error}), 403

    allowed_modes = {mode for mode, _ in HOTEL_PAYMENT_MODES}
    conn = get_db()
    try:
        for item in updates:
            entry_id = item.get("id")
            if not entry_id:
                continue
            payment_mode = (item.get("payment_mode") or "").strip()
            if payment_mode not in allowed_modes:
                return jsonify({"ok": False, "error": "Invalid payment mode."}), 400
            conn.execute(
                """UPDATE hotel_sales_ledger_entries
                   SET payment_mode = ?, updated_at = datetime('now','localtime')
                   WHERE id = ? AND company = ? AND location = ? AND sales_date = ?""",
                (payment_mode, entry_id, company, location, sales_date),
            )
        conn.commit()
        result = sync_hotel_sales_from_ledger(conn, user, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "date": sales_date,
        "ledger_entries": result["entries"],
        "sales_entries": result["sales_entries"],
        "ledger_rollup": rollup_hotel_ledger_entries(result["entries"]),
        "difference": result["difference"],
    })


@app.route("/sales_update/hotel/clear_ledger", methods=["POST"])
def clear_hotel_ledger():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", OUTLET_HOTEL)
    sales_date = data.get("date", date.today().isoformat())
    if location not in HOTEL_LOCATIONS:
        location = OUTLET_HOTEL

    lock_error = _check_sales_date_lock(user, company, location, sales_date)
    if lock_error:
        return jsonify({"ok": False, "error": lock_error}), 403

    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM hotel_sales_ledger_entries WHERE company = ? AND location = ? AND sales_date = ?",
            (company, location, sales_date),
        )
        conn.commit()
        result = sync_hotel_sales_from_ledger(conn, user, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "date": sales_date,
        "ledger_entries": [],
        "sales_entries": result["sales_entries"],
        "ledger_rollup": rollup_hotel_ledger_entries([]),
    })


def _load_outlet_entry_bundle(conn, user, company, location, sales_date, today_iso):
    is_future = sales_date > today_iso
    row = None if is_future else load_sales_row(company, location, sales_date)
    sales_entry_locked = bool(row and sales_date < today_iso and not user.get("is_admin"))
    sales_entries = row.get("sales_entry_values", {}) if row else {}
    sales_entries = build_sales_entry_values(conn, company, location, sales_date, sales_entries)
    petty_cash_counts = row.get("petty_cash_counts", {}) if row else {}
    return {
        "sales_entry_values": sales_entries,
        "sales_entry_total": get_sales_entry_total(sales_entries),
        "sales_entry_locked": sales_entry_locked,
        "petty_cash_counts": petty_cash_counts,
        "petty_cash_total": get_denomination_total(petty_cash_counts),
    }


@app.route("/sales_update")
@app.route("/sales_update/entry")
def sales_update_entry():
    user = get_current_user()
    selected_company = request.args.get("company", DEFAULT_COMPANY)
    selected_location = request.args.get("location", DEFAULT_LOCATION)
    selected_date = request.args.get("date", date.today().isoformat())
    today_iso = date.today().isoformat()

    if selected_company not in SALES_COMPANY_LOCATIONS:
        selected_company = DEFAULT_COMPANY
    locations = SALES_COMPANY_LOCATIONS[selected_company]["locations"]
    if selected_location not in locations:
        selected_location = locations[0]

    conn = get_db()
    try:
        outlet_records = {
            location: _load_outlet_entry_bundle(
                conn, user, selected_company, location, selected_date, today_iso
            )
            for location in locations
        }
        cash_transfer_entries = _sales_cash_transfer_entries(conn, selected_company, selected_location, selected_date)
        cash_transfer_total = _sales_cash_transfer_total(conn, selected_company, selected_location, selected_date)
        entry_date = _parse_sales_date(selected_date)
        kpi_bundle = _sales_report_kpi_bundle(conn, entry_date, entry_date, selected_company, None)
    finally:
        conn.close()

    selected_outlet = outlet_records[selected_location]
    sales_entries = selected_outlet["sales_entry_values"]
    sales_entry_locked = selected_outlet["sales_entry_locked"]
    sales_entry_total = selected_outlet["sales_entry_total"]

    row = None if selected_date > today_iso else load_sales_row(selected_company, selected_location, selected_date)
    petty_cash_counts = row.get("petty_cash_counts", {}) if row else {}
    cash_denomination_counts = row.get("cash_denomination_counts", {}) if row else {}
    cash_available = parse_money(sales_entries.get("cash"))
    cash_unallocated = round_half_up(max(0.0, cash_available - cash_transfer_total), 2)

    sales_record = {
        "sales_entry_values": sales_entries,
        "petty_cash_counts": petty_cash_counts,
        "cash_denomination_counts": cash_denomination_counts,
        "cash_available": cash_available,
        "cash_transfer_total": cash_transfer_total,
        "cash_unallocated": cash_unallocated,
        "cash_transfer_entries": cash_transfer_entries,
        "staff_account_entries": [],
    }

    return render_template(
        "sales_update.html",
        selected_company=selected_company,
        selected_company_label=SALES_COMPANY_LOCATIONS[selected_company]["label"],
        selected_location=selected_location,
        selected_date=selected_date,
        selected_locations=locations,
        max_sales_date=today_iso,
        sales_company_locations=SALES_COMPANY_LOCATIONS,
        sales_entry_fields=SALES_ENTRY_FIELDS,
        petty_cash_denominations=PETTY_CASH_DENOMINATIONS,
        sales_entry_total_keys=SALES_ENTRY_TOTAL_KEYS,
        sales_digital_transaction_keys=SALES_DIGITAL_TRANSACTION_KEYS,
        sales_cash_destinations=SALES_CASH_DESTINATIONS,
        sales_entry_locked=sales_entry_locked,
        sales_update_is_admin=user.get("is_admin", False),
        sales_record=sales_record,
        outlet_records=outlet_records,
        credit_employees=[],
        kpi=kpi_bundle["current"],
        kpi_trends=kpi_bundle["trends"],
        kpi_vs_label=kpi_bundle["vs_label"],
        kpi_is_single_day=kpi_bundle["is_single_day"],
        cash_panel=False,
        cash_date_from=selected_date,
        cash_date_to=selected_date,
        cash_transfer_day_collected=cash_available,
        cash_transfer_day_available=cash_unallocated,
        whatsapp_sales_report_configured=False,
        whatsapp_sales_report_company=None,
        sales_entry_total=sales_entry_total,
        de_nav_section="analytics",
        de_nav_sales_view="outlets",
    )


@app.route("/sales_update/save", methods=["POST"])
def save_sales_update():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    data = request.get_json(silent=True) or {}
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", date.today().isoformat())
    sales_entries = data.get("sales_entries", {})
    petty_cash_counts = data.get("petty_cash_counts", {})
    cash_denomination_counts = data.get("cash_denomination_counts", {})
    sales_only = bool(data.get("sales_only"))

    lock_error = _check_sales_date_lock(user, company, location, sales_date)
    if lock_error:
        return jsonify({"ok": False, "error": lock_error}), 403 if "administrator" in lock_error else 400

    conn = get_db()
    try:
        sales_entries = build_sales_entry_values(conn, company, location, sales_date, sales_entries)
    finally:
        conn.close()

    existing_row = load_sales_row(company, location, sales_date)
    if sales_only:
        petty_cash_counts = (existing_row or {}).get("petty_cash_counts", {})
        cash_denomination_counts = (existing_row or {}).get("cash_denomination_counts", {})
    elif not cash_denomination_counts:
        cash_denomination_counts = (existing_row or {}).get("cash_denomination_counts", {})

    if cash_denomination_counts:
        cash_total = get_denomination_total(cash_denomination_counts)
        if cash_total > 0:
            sales_entries["cash"] = round_half_up(cash_total, 2)

    totals = upsert_sales_row(user, company, location, sales_date, sales_entries, petty_cash_counts, cash_denomination_counts)

    return jsonify({
        "ok": True,
        "company": company,
        "location": location,
        "date": sales_date,
        "sales_entries": sales_entries,
        "sales_entry_total": totals["sales_entry_total"],
        "petty_cash_total": totals["petty_cash_total"],
    })


@app.route("/sales_update/upload_report", methods=["POST"])
def upload_sales_report():
    user = get_current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not authenticated"}), 401

    sales_date_str = (request.form.get("date") or date.today().isoformat()).strip()
    sales_date = _parse_sales_date(sales_date_str)
    active_location = (request.form.get("location") or DEFAULT_LOCATION).strip()
    upload = request.files.get("report_file")

    if not upload or not upload.filename:
        return jsonify({"ok": False, "error": "Please choose an Excel report file."}), 400

    try:
        parsed = parse_order_invoice_report(upload.stream, sales_date)
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Could not read report: {exc}"}), 400

    company = DEFAULT_COMPANY
    results = {}

    for outlet in (OUTLET_BAR, OUTLET_RESTAURANT):
        existing_row = load_sales_row(company, outlet, sales_date.isoformat())
        existing_values = (existing_row or {}).get("sales_entry_values", {})
        merged = merge_import_into_sales_values(existing_values, parsed[outlet])

        conn = get_db()
        try:
            merged = build_sales_entry_values(conn, company, outlet, sales_date.isoformat(), merged)
        finally:
            conn.close()

        petty = (existing_row or {}).get("petty_cash_counts", {})
        cash_denoms = (existing_row or {}).get("cash_denomination_counts", {})
        upsert_sales_row(user, company, outlet, sales_date.isoformat(), merged, petty, cash_denoms)
        results[outlet.lower()] = merged

    return jsonify({
        "ok": True,
        "date": sales_date.isoformat(),
        "bar": results.get("bar", {}),
        "restaurant": results.get("restaurant", {}),
        "active_location": active_location,
        "meta": parsed.get("meta", {}),
        "message": f"Report imported — Bar and Restaurant updated for {sales_date.isoformat()}",
    })


@app.route("/sales_update/add_expense", methods=["POST"])
def sales_update_add_expense():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")
    description = (data.get("description") or "").strip()
    amount = parse_money(data.get("amount"))

    lock_error = _check_sales_date_lock(user, company, location, sales_date)
    if lock_error:
        return jsonify({"ok": False, "error": lock_error}), 403

    if not description or amount <= 0:
        return jsonify({"ok": False, "error": "Description and positive amount are required."}), 400

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO sales_update_expenses (company, location, sales_date, description, amount) VALUES (?, ?, ?, ?, ?)",
            (company, location, sales_date, description, amount),
        )
        conn.commit()
        expense_total = _sales_expense_total(conn, company, location, sales_date)
        expense_entries = _sales_expense_entries(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "expense_total": expense_total, "expense_entries": expense_entries})


@app.route("/sales_update/edit_expense", methods=["POST"])
def sales_update_edit_expense():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    expense_id = data.get("id")
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")
    description = (data.get("description") or "").strip()
    amount = parse_money(data.get("amount"))

    lock_error = _check_sales_date_lock(user, company, location, sales_date)
    if lock_error:
        return jsonify({"ok": False, "error": lock_error}), 403

    conn = get_db()
    try:
        conn.execute(
            "UPDATE sales_update_expenses SET description=?, amount=?, updated_at=datetime('now','localtime') WHERE id=? AND company=? AND location=? AND sales_date=?",
            (description, amount, expense_id, company, location, sales_date),
        )
        conn.commit()
        expense_total = _sales_expense_total(conn, company, location, sales_date)
        expense_entries = _sales_expense_entries(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "expense_total": expense_total, "expense_entries": expense_entries})


@app.route("/sales_update/delete_expense", methods=["POST"])
def sales_update_delete_expense():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    expense_id = data.get("id")
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")

    lock_error = _check_sales_date_lock(user, company, location, sales_date)
    if lock_error:
        return jsonify({"ok": False, "error": lock_error}), 403

    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM sales_update_expenses WHERE id=? AND company=? AND location=? AND sales_date=?",
            (expense_id, company, location, sales_date),
        )
        conn.commit()
        expense_total = _sales_expense_total(conn, company, location, sales_date)
        expense_entries = _sales_expense_entries(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "expense_total": expense_total, "expense_entries": expense_entries})


@app.route("/sales_update/add_unpaid_bill", methods=["POST"])
def sales_update_add_unpaid_bill():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")
    invoice_number = (data.get("invoice_number") or "").strip()
    amount = parse_money(data.get("amount"))

    if not invoice_number or amount <= 0:
        return jsonify({"ok": False, "error": "Invoice number and positive amount are required."}), 400

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO sales_update_pending_bills
               (company, location, recorded_sales_date, invoice_number, amount, status)
               VALUES (?, ?, ?, ?, ?, 'open')""",
            (company, location, sales_date, invoice_number, amount),
        )
        conn.commit()
        total = _sales_unpaid_bill_total(conn, company, location, sales_date)
        entries = _sales_unpaid_bill_entries(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "unpaid_pending_bill_total": total, "unpaid_bill_entries": entries})


@app.route("/sales_update/delete_unpaid_bill", methods=["POST"])
def sales_update_delete_unpaid_bill():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    bill_id = data.get("id")
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")

    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM sales_update_pending_bills WHERE id=? AND company=? AND location=? AND recorded_sales_date=?",
            (bill_id, company, location, sales_date),
        )
        conn.commit()
        total = _sales_unpaid_bill_total(conn, company, location, sales_date)
        entries = _sales_unpaid_bill_entries(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "unpaid_pending_bill_total": total, "unpaid_bill_entries": entries})


@app.route("/sales_update/open_pending_bills", methods=["GET"])
def sales_update_open_pending_bills():
    company = request.args.get("company", DEFAULT_COMPANY)
    location = request.args.get("location", DEFAULT_LOCATION)
    conn = get_db()
    try:
        bills = _sales_open_pending_bills(conn, company, location)
    finally:
        conn.close()
    return jsonify({"ok": True, "open_pending_bills": bills})


@app.route("/sales_update/add_bill_payment", methods=["POST"])
def sales_update_add_bill_payment():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")
    pending_bill_id = data.get("pending_bill_id")
    amount = parse_money(data.get("amount"))

    conn = get_db()
    try:
        conn.execute(
            "INSERT INTO sales_update_bill_payments (company, location, sales_date, pending_bill_id, amount) VALUES (?, ?, ?, ?, ?)",
            (company, location, sales_date, pending_bill_id, amount),
        )
        conn.execute(
            "UPDATE sales_update_pending_bills SET status='cleared', cleared_sales_date=? WHERE id=?",
            (sales_date, pending_bill_id),
        )
        conn.commit()
        total = _sales_bill_payment_total(conn, company, location, sales_date)
        entries = _sales_bill_payment_entries(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "previous_bill_payment_total": total, "bill_payment_entries": entries})


@app.route("/sales_update/add_cash_transfer", methods=["POST"])
def sales_update_add_cash_transfer():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")
    destination = (data.get("destination") or "bank").strip().lower()
    description = (data.get("description") or "").strip()
    amount = parse_money(data.get("amount"))

    if amount <= 0:
        return jsonify({"ok": False, "error": "Amount must be greater than zero."}), 400

    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO sales_update_cash_transfers
               (company, location, sales_date, destination, description, amount)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (company, location, sales_date, destination, description, amount),
        )
        conn.commit()
        entries = _sales_cash_transfer_entries(conn, company, location, sales_date)
        total = _sales_cash_transfer_total(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "cash_transfer_total": total, "cash_transfer_entries": entries})


@app.route("/sales_update/delete_cash_transfer", methods=["POST"])
def sales_update_delete_cash_transfer():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    transfer_id = data.get("id")
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")

    conn = get_db()
    try:
        conn.execute(
            "DELETE FROM sales_update_cash_transfers WHERE id=? AND company=? AND location=? AND sales_date=?",
            (transfer_id, company, location, sales_date),
        )
        conn.commit()
        entries = _sales_cash_transfer_entries(conn, company, location, sales_date)
        total = _sales_cash_transfer_total(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "cash_transfer_total": total, "cash_transfer_entries": entries})


@app.route("/sales_update/delete_bill_payment", methods=["POST"])
def sales_update_delete_bill_payment():
    user = get_current_user()
    data = request.get_json(silent=True) or {}
    payment_id = data.get("id")
    company = data.get("company", DEFAULT_COMPANY)
    location = data.get("location", DEFAULT_LOCATION)
    sales_date = data.get("date", "")

    conn = get_db()
    try:
        row = conn.execute(
            "SELECT pending_bill_id FROM sales_update_bill_payments WHERE id=? AND company=? AND location=? AND sales_date=?",
            (payment_id, company, location, sales_date),
        ).fetchone()
        if row:
            conn.execute(
                "UPDATE sales_update_pending_bills SET status='open', cleared_sales_date=NULL WHERE id=?",
                (row["pending_bill_id"],),
            )
        conn.execute(
            "DELETE FROM sales_update_bill_payments WHERE id=? AND company=? AND location=? AND sales_date=?",
            (payment_id, company, location, sales_date),
        )
        conn.commit()
        total = _sales_bill_payment_total(conn, company, location, sales_date)
        entries = _sales_bill_payment_entries(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({"ok": True, "previous_bill_payment_total": total, "bill_payment_entries": entries})


@app.route("/sales_update/send_whatsapp_report", methods=["POST"])
def sales_update_send_whatsapp_report():
    return jsonify({"ok": False, "error": "WhatsApp report is not configured."}), 501


if __name__ == "__main__":
    init_db()
    app.run(debug=True, host="127.0.0.1", port=8002)
