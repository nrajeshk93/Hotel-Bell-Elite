"""Mobile JSON APIs for Employee Payroll (v1).

Additive routes under /api/mobile/payroll/*. Web Employee / Attendance / Credit /
Tips pages are unchanged. Report submodule is not exposed here.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, datetime

from flask import Blueprint, jsonify, request

from db import SQL_NOW, get_db, hbe_rank_records
from workspace_access import user_can_access_payroll_submodule

payroll_mobile_bp = Blueprint("payroll_mobile", __name__)

_ALLOWED_ATT_STATUS = ("present", "absent", "half_day", "")
_CORE_STATUS = ("active", "inactive")


def _current_user():
    import app as app_module

    return app_module.get_current_user()


def _json_error(message, status=400, **extra):
    payload = {"ok": False, "error": str(message or "Request failed.")}
    payload.update(extra)
    return jsonify(payload), status


def _require_login():
    user = _current_user()
    if not user:
        return None, _json_error("Not signed in", 401)
    return user, None


def _require_submodule(user, key):
    if not user_can_access_payroll_submodule(user, key):
        return _json_error("You do not have access to this module.", 403)
    return None


def _lean_payroll_state(state):
    state = state or {}
    return {
        "locked": bool(state.get("locked")),
        "can_edit": bool(state.get("can_edit")),
        "label": state.get("label") or "",
        "message": state.get("message") or "",
        "status_label": state.get("status_label") or "",
    }


def _money(value):
    try:
        return round(float(value or 0), 2)
    except (TypeError, ValueError):
        return 0.0


def _request_json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _employee_lean(emp):
    att = emp.get("att") if isinstance(emp.get("att"), dict) else {}
    return {
        "id": int(emp.get("id") or 0),
        "emp_code": emp.get("emp_code") or "",
        "name": emp.get("name") or "",
        "company": emp.get("company") or "",
        "location": emp.get("location") or "",
        "mobile": emp.get("mobile") or "",
        "status": emp.get("status") or "",
        "gross_salary": _money(emp.get("gross_salary")),
        "net_salary": _money(emp.get("net")),
        "present": att.get("present"),
        "absent": att.get("absent"),
        "half_day": att.get("half_day_marked", att.get("half_day")),
        "credit_balance": _money(emp.get("credit_total", emp.get("credit_balance"))),
    }


def _validate_name_mobile(name, mobile):
    errors = []
    if not name:
        errors.append("Employee Name is required.")
    if not re.match(r"^\d{10}$", mobile or ""):
        errors.append("Mobile number must be exactly 10 digits.")
    return errors


def _parse_iso_date(value, fallback=None):
    text = str(value or "").strip()
    if not text:
        return fallback
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return fallback


# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------


@payroll_mobile_bp.route(
    "/api/mobile/payroll/employees",
    methods=["GET"],
    endpoint="mobile_payroll_employees",
)
def mobile_payroll_employees():
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "employee")
    if denied:
        return denied

    from employee_payroll import (
        _load_employees_list_context,
        _period_label,
        _get_locations,
    )

    ctx = _load_employees_list_context()
    year = int(ctx["sel_year"])
    month = int(ctx["sel_month"])
    employees = [_employee_lean(e) for e in ctx.get("employees") or []]
    return jsonify({
        "ok": True,
        "year": year,
        "month": month,
        "period_label": _period_label(year, month),
        "payroll_state": _lean_payroll_state(ctx.get("payroll_state")),
        "status": ctx.get("sel_status") or "active",
        "location": ctx.get("sel_location") or "",
        "locations": list(_get_locations()),
        "search": ctx.get("search") or "",
        "employees": employees,
    })


@payroll_mobile_bp.route(
    "/api/mobile/payroll/employees/<int:emp_id>",
    methods=["GET"],
    endpoint="mobile_payroll_employee_detail",
)
def mobile_payroll_employee_detail(emp_id):
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "employee")
    if denied:
        return denied

    from employee_payroll import (
        _attach_employee_month_context,
        _get_locations,
        _get_payroll_month_state,
        _period_from_source,
        _period_label,
        _employee_has_locked_month_data,
    )

    year, month = _period_from_source(request.args)
    conn = get_db()
    try:
        row = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not row:
            return _json_error("Employee not found.", 404)
        payroll_state = _get_payroll_month_state(conn, year, month)
        emp = _attach_employee_month_context(conn, row, year, month, payroll_state=payroll_state)
        locked_wages = bool(_employee_has_locked_month_data(conn, emp_id))
    finally:
        conn.close()

    payload = _employee_lean(emp)
    payload.update({
        "ok": True,
        "year": year,
        "month": month,
        "period_label": _period_label(year, month),
        "payroll_state": _lean_payroll_state(payroll_state),
        "payroll_fields_locked": locked_wages,
        "locations": list(_get_locations()),
        "address": emp.get("address") or "",
        "sex": emp.get("sex") or "",
        "total_off": int(emp.get("total_off") or 0),
        "gross_actual": _money(emp.get("gross_actual")),
        "basic": _money(emp.get("basic")),
        "epf": _money(emp.get("epf")),
        "esic": _money(emp.get("esic")),
        "lop_deduction": _money(emp.get("lop_deduction")),
        "lop_days": emp.get("lop_days") if emp.get("lop_days") is not None else 0,
        "sunday_incentive": _money(emp.get("sunday_incentive")),
        "tip_incentive": _money(emp.get("tip_incentive")),
        "credit_repayment": _money(emp.get("credit_repayment")),
        "epf_exempt": bool(emp.get("epf_exempt")),
        "esic_exempt": bool(emp.get("esic_exempt")),
    })
    return jsonify(payload)


@payroll_mobile_bp.route(
    "/api/mobile/payroll/employees",
    methods=["POST"],
    endpoint="mobile_payroll_employee_create",
)
def mobile_payroll_employee_create():
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "employee")
    if denied:
        return denied

    from employee_payroll import (
        _DEFAULT_COMPANY,
        _get_locations,
        _next_emp_code,
        _emp_code_taken,
    )

    data = _request_json()
    name = str(data.get("name") or "").strip()
    mobile = str(data.get("mobile") or "").strip()
    company = str(data.get("company") or "").strip() or _DEFAULT_COMPANY
    location = str(data.get("location") or "").strip()
    locations = set(_get_locations())
    if location and location not in locations:
        return _json_error("Choose a valid location.")
    try:
        salary_val = float(data.get("gross_salary") or 0)
        if salary_val < 0:
            return _json_error("Salary must be a positive number.")
    except (TypeError, ValueError):
        return _json_error("Salary must be a valid number.")
    status = str(data.get("status") or "active").strip().lower()
    if status not in _CORE_STATUS:
        status = "active"

    errors = _validate_name_mobile(name, mobile)
    if errors:
        return _json_error(errors[0])

    conn = get_db()
    try:
        emp_code = _next_emp_code(conn)
        if _emp_code_taken(conn, emp_code):
            return _json_error("Could not assign a unique Employee ID. Please try again.")
        cursor = conn.execute(
            """INSERT INTO employees
               (emp_code, name, company, location, mobile, gross_salary, status)
               VALUES (?,?,?,?,?,?,?)""",
            (emp_code, name, company, location, mobile, salary_val, status),
        )
        emp_id = int(cursor.lastrowid)
        conn.commit()
    finally:
        conn.close()
    return jsonify({
        "ok": True,
        "id": emp_id,
        "emp_code": emp_code,
        "name": name,
        "company": company,
        "location": location,
        "mobile": mobile,
        "gross_salary": _money(salary_val),
        "status": status,
    })


@payroll_mobile_bp.route(
    "/api/mobile/payroll/employees/<int:emp_id>",
    methods=["POST"],
    endpoint="mobile_payroll_employee_update",
)
def mobile_payroll_employee_update(emp_id):
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "employee")
    if denied:
        return denied

    from employee_payroll import (
        _DEFAULT_COMPANY,
        _employee_has_locked_month_data,
        _freeze_employee_wages_for_locked_months,
        _get_locations,
        _wage_fields_changed,
    )

    data = _request_json()
    conn = get_db()
    try:
        existing = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not existing:
            return _json_error("Employee not found.", 404)
        existing = dict(existing)

        name = str(data.get("name", existing.get("name") or "")).strip()
        mobile = str(data.get("mobile", existing.get("mobile") or "")).strip()
        company = str(data.get("company", existing.get("company") or "")).strip() or _DEFAULT_COMPANY
        location = str(data.get("location", existing.get("location") or "")).strip()
        locations = set(_get_locations())
        if location and location not in locations:
            return _json_error("Choose a valid location.")
        status = str(data.get("status", existing.get("status") or "active")).strip().lower()
        if status not in _CORE_STATUS:
            status = existing.get("status") or "active"

        errors = _validate_name_mobile(name, mobile)
        if errors:
            return _json_error(errors[0])

        salary_val = float(existing.get("gross_salary") or 0)
        if "gross_salary" in data:
            try:
                salary_val = float(data.get("gross_salary") or 0)
                if salary_val < 0:
                    return _json_error("Salary must be a positive number.")
            except (TypeError, ValueError):
                return _json_error("Salary must be a valid number.")

        locked = _employee_has_locked_month_data(conn, emp_id)
        new_wage_vals = {
            "gross_salary": salary_val,
            "basic_salary": existing.get("basic_salary") or 0,
            "epf_amount": existing.get("epf_amount") or 0,
            "esic_amount": existing.get("esic_amount") or 0,
            "epf_exempt": existing.get("epf_exempt") or 0,
            "esic_exempt": existing.get("esic_exempt") or 0,
            "total_off": existing.get("total_off") or 0,
        }
        if locked and _wage_fields_changed(existing, new_wage_vals):
            salary_val = float(existing.get("gross_salary") or 0)
        elif _wage_fields_changed(existing, new_wage_vals):
            _freeze_employee_wages_for_locked_months(conn, emp_id, existing)

        conn.execute(
            f"""UPDATE employees SET name=?, company=?, location=?, mobile=?,
                gross_salary=?, status=?, updated_at={SQL_NOW} WHERE id=?""",
            (name, company, location, mobile, salary_val, status, emp_id),
        )
        conn.commit()
    finally:
        conn.close()
    return jsonify({
        "ok": True,
        "id": emp_id,
        "emp_code": existing.get("emp_code") or "",
        "name": name,
        "company": company,
        "location": location,
        "mobile": mobile,
        "gross_salary": _money(salary_val),
        "status": status,
    })


# ---------------------------------------------------------------------------
# Attendance — date view is primary; month overview is secondary
# ---------------------------------------------------------------------------


def _attendance_date_payload(conn, user, sel_dt, q="", location=""):
    from employee_payroll import (
        _append_attendance_scope_conditions,
        _attendance_filter_options,
        _can_modify_attendance_record,
        _EMPLOYEE_DISPLAY_ORDER,
        _get_payroll_month_state,
        _attendance_date_lock_message,
        _period_label,
    )

    today_dt = date.today()
    date_str = sel_dt.isoformat()
    is_future = sel_dt > today_dt
    year, month = sel_dt.year, sel_dt.month

    base_conds, base_params = ["status='active'"], []
    _append_attendance_scope_conditions(base_conds, base_params, user)
    if location:
        base_conds.append("location=?")
        base_params.append(location)
    conds = list(base_conds)
    params = list(base_params)
    if q:
        conds.append("(name LIKE ? OR emp_code LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])

    rows = conn.execute(
        f"SELECT * FROM employees WHERE {' AND '.join(conds)} ORDER BY {_EMPLOYEE_DISPLAY_ORDER}",
        params,
    ).fetchall()
    if q:
        rows = hbe_rank_records(rows, q, ("name", "emp_code", "mobile", "location"))

    payroll_state = _get_payroll_month_state(conn, year, month)
    payroll_locked = bool(payroll_state["locked"])
    now_dt = datetime.now()
    employees = []
    present_count = absent_count = half_count = unmarked_count = 0
    for r in rows:
        e = dict(r)
        rec = None
        if is_future:
            date_status = ""
        else:
            rec = conn.execute(
                "SELECT status, updated_at FROM attendance WHERE employee_id=? AND date=?",
                (e["id"], date_str),
            ).fetchone()
            date_status = rec["status"] if rec else ""
        can_modify = (not is_future) and _can_modify_attendance_record(
            user, sel_dt, rec, today=today_dt, now=now_dt, payroll_locked=payroll_locked
        )
        if date_status == "present":
            present_count += 1
        elif date_status == "absent":
            absent_count += 1
        elif date_status == "half_day":
            half_count += 1
        else:
            unmarked_count += 1
        employees.append({
            "id": int(e["id"]),
            "emp_code": e.get("emp_code") or "",
            "name": e.get("name") or "",
            "location": e.get("location") or "",
            "company": e.get("company") or "",
            "date_status": date_status,
            "can_modify": bool(can_modify),
        })

    return {
        "ok": True,
        "view": "date",
        "date": date_str,
        "year": year,
        "month": month,
        "period_label": _period_label(year, month),
        "is_future": is_future,
        "payroll_state": _lean_payroll_state(payroll_state),
        "lock_message": _attendance_date_lock_message(
            today_dt, payroll_locked=payroll_locked, year=year, month=month
        ),
        "locations": _attendance_filter_options(conn, user),
        "search": q,
        "location": location,
        "present_count": present_count,
        "absent_count": absent_count,
        "half_count": half_count,
        "unmarked_count": unmarked_count,
        "employees": employees,
        "ok": True,
    }


def _attendance_month_payload(conn, user, year, month, q="", location=""):
    from employee_payroll import (
        _append_attendance_scope_conditions,
        _attach_employee_month_context,
        _attendance_filter_options,
        _EMPLOYEE_DISPLAY_ORDER,
        _get_payroll_month_state,
        _period_label,
    )

    conditions = ["status='active'"]
    params = []
    _append_attendance_scope_conditions(conditions, params, user)
    if location:
        conditions.append("location = ?")
        params.append(location)
    if q:
        conditions.append("(name LIKE ? OR emp_code LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    where = " WHERE " + " AND ".join(conditions)
    rows = conn.execute(
        f"SELECT * FROM employees{where} ORDER BY {_EMPLOYEE_DISPLAY_ORDER}",
        tuple(params),
    ).fetchall()
    if q:
        rows = hbe_rank_records(rows, q, ("name", "emp_code", "mobile", "location"))
    payroll_state = _get_payroll_month_state(conn, year, month)
    employees = []
    for r in rows:
        e = _attach_employee_month_context(conn, r, year, month, payroll_state=payroll_state)
        att = e.get("att") or {}
        employees.append({
            "id": int(e["id"]),
            "emp_code": e.get("emp_code") or "",
            "name": e.get("name") or "",
            "location": e.get("location") or "",
            "present": att.get("present"),
            "absent": att.get("absent"),
            "half_day": att.get("half_day_marked", att.get("half_day")),
            "tracked": bool(att.get("tracked")),
        })
    return {
        "ok": True,
        "view": "month",
        "year": year,
        "month": month,
        "period_label": _period_label(year, month),
        "payroll_state": _lean_payroll_state(payroll_state),
        "locations": _attendance_filter_options(conn, user),
        "search": q,
        "location": location,
        "employees": employees,
    }


@payroll_mobile_bp.route(
    "/api/mobile/payroll/attendance",
    methods=["GET"],
    endpoint="mobile_payroll_attendance",
)
def mobile_payroll_attendance():
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "attendance")
    if denied:
        return denied

    from employee_payroll import _period_from_source

    q = (request.args.get("q") or "").strip()
    location = (request.args.get("location") or "").strip()
    view = (request.args.get("view") or "").strip().lower()
    date_arg = (request.args.get("date") or "").strip()

    conn = get_db()
    try:
        if view == "month" and not date_arg:
            year, month = _period_from_source(request.args)
            payload = _attendance_month_payload(conn, user, year, month, q=q, location=location)
        else:
            sel_dt = _parse_iso_date(date_arg, fallback=date.today())
            payload = _attendance_date_payload(conn, user, sel_dt, q=q, location=location)
    finally:
        conn.close()
    return jsonify(payload)


@payroll_mobile_bp.route(
    "/api/mobile/payroll/attendance/<int:emp_id>",
    methods=["GET"],
    endpoint="mobile_payroll_attendance_detail",
)
def mobile_payroll_attendance_detail(emp_id):
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "attendance")
    if denied:
        return denied

    from employee_payroll import (
        _attach_employee_month_context,
        _can_modify_attendance_record,
        _get_payroll_month_state,
        _period_from_source,
        _period_label,
        _user_can_access_attendance_employee,
        _attendance_date_lock_message,
    )

    year, month = _period_from_source(request.args)
    conn = get_db()
    try:
        emp = conn.execute("SELECT * FROM employees WHERE id=?", (emp_id,)).fetchone()
        if not emp:
            return _json_error("Employee not found.", 404)
        if not _user_can_access_attendance_employee(conn, emp_id, user=user):
            return _json_error("You do not have access to this employee attendance.", 403)
        payroll_state = _get_payroll_month_state(conn, year, month)
        payroll_locked = bool(payroll_state["locked"])
        emp = _attach_employee_month_context(conn, emp, year, month, payroll_state=payroll_state)
        att = emp.get("att") or {}
        _, num_days = calendar.monthrange(year, month)
        today_dt = date.today()
        now_dt = datetime.now()
        days = []
        for day in range(1, num_days + 1):
            d_str = f"{year}-{month:02d}-{day:02d}"
            status = (att.get("records") or {}).get(d_str, "")
            att_dt = date(year, month, day)
            record = (att.get("record_meta") or {}).get(d_str)
            can_edit = _can_modify_attendance_record(
                user, att_dt, record, today=today_dt, now=now_dt, payroll_locked=payroll_locked
            )
            days.append({
                "day": day,
                "date": d_str,
                "status": status or "",
                "can_edit": bool(can_edit),
                "is_future": att_dt > today_dt,
            })
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "employee": _employee_lean(emp),
        "year": year,
        "month": month,
        "period_label": _period_label(year, month),
        "payroll_state": _lean_payroll_state(payroll_state),
        "lock_message": _attendance_date_lock_message(
            payroll_locked=payroll_locked, year=year, month=month
        ),
        "present": att.get("present"),
        "absent": att.get("absent"),
        "half_day": att.get("half_day_marked", att.get("half_day")),
        "days": days,
    })


@payroll_mobile_bp.route(
    "/api/mobile/payroll/attendance/mark",
    methods=["POST"],
    endpoint="mobile_payroll_attendance_mark",
)
def mobile_payroll_attendance_mark():
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "attendance")
    if denied:
        return denied

    from employee_payroll import (
        _attendance_date_lock_message,
        _can_modify_attendance_record,
        _is_payroll_month_locked,
        _parse_attendance_date,
        _payroll_month_frozen_message,
        _user_can_access_attendance_employee,
    )

    data = _request_json()
    try:
        emp_id = int(data.get("employee_id") or 0)
    except (TypeError, ValueError):
        emp_id = 0
    att_date = str(data.get("date") or "").strip()
    status = str(data.get("status") if data.get("status") is not None else "").strip()
    if status not in _ALLOWED_ATT_STATUS:
        return _json_error("Status must be present, absent, half_day, or empty to clear.")
    if not emp_id or not att_date:
        return _json_error("employee_id and date are required.")

    att_dt = _parse_attendance_date(att_date)
    if not att_dt:
        return _json_error("Invalid date.")
    today_dt = date.today()
    if att_dt > today_dt:
        return _json_error("Future attendance cannot be marked.")

    conn = get_db()
    try:
        if not _user_can_access_attendance_employee(conn, emp_id, user=user):
            return _json_error("You do not have access to this employee attendance.", 403)
        payroll_locked = _is_payroll_month_locked(conn, att_dt.year, att_dt.month)
        if payroll_locked:
            return _json_error(
                _payroll_month_frozen_message(att_dt.year, att_dt.month),
                403,
                locked=True,
            )
        rec = conn.execute(
            "SELECT status, updated_at FROM attendance WHERE employee_id=? AND date=?",
            (emp_id, att_date),
        ).fetchone()
        if not _can_modify_attendance_record(
            user, att_dt, rec, today=today_dt, now=datetime.now(), payroll_locked=payroll_locked
        ):
            return _json_error(_attendance_date_lock_message(today_dt), 403)
        if status == "":
            conn.execute(
                "DELETE FROM attendance WHERE employee_id=? AND date=?",
                (emp_id, att_date),
            )
        else:
            conn.execute(
                f"INSERT INTO attendance (employee_id, date, status, created_at, updated_at) "
                f"VALUES (?,?,?,{SQL_NOW},{SQL_NOW}) "
                f"ON CONFLICT(employee_id, date) DO UPDATE SET status=excluded.status, updated_at={SQL_NOW}",
                (emp_id, att_date, status),
            )
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "employee_id": emp_id, "date": att_date, "status": status})


# ---------------------------------------------------------------------------
# Credits
# ---------------------------------------------------------------------------


@payroll_mobile_bp.route(
    "/api/mobile/payroll/credits",
    methods=["GET"],
    endpoint="mobile_payroll_credits",
)
def mobile_payroll_credits():
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "credit")
    if denied:
        return denied

    from employee_payroll import (
        _EMPLOYEE_DISPLAY_ORDER,
        _get_payroll_month_state,
        _period_from_source,
        _period_label,
        _round_half_up,
        _annotate_credit_editability,
    )

    year, month = _period_from_source(request.args)
    conn = get_db()
    try:
        payroll_state = _get_payroll_month_state(conn, year, month)
        credit_emps = conn.execute(
            """
            SELECT e.id, e.name, e.emp_code, e.company, e.location,
                   COALESCE(SUM(c.amount), 0) AS credit_balance,
                   COUNT(c.id) AS credit_entries
            FROM employees e
            LEFT JOIN credits c ON e.id = c.employee_id
            GROUP BY e.id
            HAVING COALESCE(SUM(c.amount), 0) > 0
            ORDER BY
                COALESCE(SUM(c.amount), 0) DESC,
                LOWER(e.company), LOWER(e.location), LOWER(e.name), e.id DESC
            """
        ).fetchall()
        employees = [
            {
                "id": int(row["id"]),
                "name": row["name"] or "",
                "emp_code": row["emp_code"] or "",
                "company": row["company"] or "",
                "location": row["location"] or "",
                "credit_balance": _round_half_up(row["credit_balance"] or 0, 2),
                "credit_entries": int(row["credit_entries"] or 0),
            }
            for row in credit_emps
        ]
        total_credit_amount = _round_half_up(sum(e["credit_balance"] for e in employees), 2)
        recent_rows = conn.execute(
            """
            SELECT c.id, c.date, c.description, c.amount,
                   e.id AS emp_id, e.name AS emp_name, e.emp_code, e.company
            FROM credits c
            JOIN employees e ON c.employee_id = e.id
            ORDER BY c.date DESC, c.id DESC
            LIMIT 15
            """
        ).fetchall()
        recent = [
            {
                "id": int(r["id"]),
                "date": r["date"] or "",
                "description": r["description"] or "",
                "amount": _money(r["amount"]),
                "employee_id": int(r["emp_id"]),
                "emp_name": r["emp_name"] or "",
                "emp_code": r["emp_code"] or "",
                "can_edit": bool(item.get("can_edit")),
            }
            for r, item in zip(
                recent_rows,
                _annotate_credit_editability(conn, recent_rows),
            )
        ]
        all_employees = [
            {
                "id": int(r["id"]),
                "name": r["name"] or "",
                "emp_code": r["emp_code"] or "",
            }
            for r in conn.execute(
                f"SELECT id, name, emp_code FROM employees WHERE status='active' ORDER BY {_EMPLOYEE_DISPLAY_ORDER}"
            ).fetchall()
        ]
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "year": year,
        "month": month,
        "period_label": _period_label(year, month),
        "payroll_state": _lean_payroll_state(payroll_state),
        "total_credit_amount": total_credit_amount,
        "employees": employees,
        "recent": recent,
        "all_employees": all_employees,
    })


@payroll_mobile_bp.route(
    "/api/mobile/payroll/credits/<int:emp_id>",
    methods=["GET"],
    endpoint="mobile_payroll_credit_employee",
)
def mobile_payroll_credit_employee(emp_id: int):
    """Credit transactions for one employee (full history)."""
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "credit")
    if denied:
        return denied

    from employee_payroll import (
        _annotate_credit_editability,
        _get_employee_credits,
        _get_total_credits,
        _round_half_up,
    )

    conn = get_db()
    try:
        emp = conn.execute(
            """
            SELECT id, name, emp_code, company, location, status
            FROM employees WHERE id=?
            """,
            (emp_id,),
        ).fetchone()
        if not emp:
            return _json_error("Employee not found.", 404)
        bundle = _get_employee_credits(conn, emp_id)
        items_raw = bundle.get("items") or []
        annotated = _annotate_credit_editability(conn, items_raw)
        entries = []
        for row in annotated:
            amount = _round_half_up(row.get("amount") or 0, 2)
            entry_type = str(row.get("entry_type") or "")
            txn_type = "repayment" if amount < 0 or "repay" in entry_type.lower() else "credit"
            entries.append({
                "id": int(row["id"]),
                "date": row.get("date") or "",
                "description": row.get("description") or "",
                "amount": amount,
                "entry_type": entry_type,
                "transaction_type": txn_type,
                "can_edit": bool(row.get("can_edit")),
            })
        balance = _round_half_up(_get_total_credits(conn, emp_id), 2)
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "employee": {
            "id": int(emp["id"]),
            "name": emp["name"] or "",
            "emp_code": emp["emp_code"] or "",
            "company": emp["company"] or "",
            "location": emp["location"] or "",
            "status": emp["status"] or "",
        },
        "credit_balance": balance,
        "entries": entries,
        "entry_count": len(entries),
    })


@payroll_mobile_bp.route(
    "/api/mobile/payroll/credits",
    methods=["POST"],
    endpoint="mobile_payroll_credit_create",
)
def mobile_payroll_credit_create():
    """Add credit/repayment. Advances sync to sales_update_expenses. No unlock."""
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "credit")
    if denied:
        return denied

    from employee_payroll import (
        _is_credit_date_locked,
        _parse_credit_expense_payment,
        _payroll_month_frozen_message,
        _period_from_credit_date,
        _post_credit_advance_expense,
    )

    data = _request_json()
    try:
        emp_id_val = int(data.get("employee_id") or 0)
        raw_amount = abs(float(data.get("amount") or 0))
    except (TypeError, ValueError):
        return _json_error("Valid employee_id and amount are required.")
    cr_date = str(data.get("date") or "").strip()
    description = str(data.get("description") or "").strip()
    txn_type = str(data.get("transaction_type") or "credit").strip().lower()
    if txn_type not in ("credit", "repayment"):
        return _json_error("transaction_type must be credit or repayment.")
    if not cr_date or raw_amount <= 0 or emp_id_val <= 0:
        return _json_error("employee_id, date, and amount greater than 0 are required.")
    if not _parse_iso_date(cr_date):
        return _json_error("Invalid date.")

    is_repayment = txn_type == "repayment"
    amount_val = -raw_amount if is_repayment else raw_amount
    entry_type = "manual_repayment" if is_repayment else "manual"
    if is_repayment and not description:
        description = "Repayment"

    payment_type, transaction_id = _parse_credit_expense_payment(data)
    import app as app_module

    if not is_repayment:
        if payment_type == app_module.EXPENSE_PAYMENT_BANK and not transaction_id:
            return _json_error("Transaction ID is required for bank transfer advances.")

    conn = get_db()
    try:
        if _is_credit_date_locked(conn, cr_date):
            year, month = _period_from_credit_date(cr_date)
            return _json_error(
                _payroll_month_frozen_message(year, month) if year else "This payroll month is locked.",
                403,
                locked=True,
            )
        emp = conn.execute(
            "SELECT id, name FROM employees WHERE id=?", (emp_id_val,)
        ).fetchone()
        if not emp:
            return _json_error("Employee not found.", 404)
        cursor = conn.execute(
            "INSERT INTO credits (employee_id, date, description, amount, entry_type) VALUES (?,?,?,?,?)",
            (emp_id_val, cr_date, description, amount_val, entry_type),
        )
        credit_id = cursor.lastrowid
        if not is_repayment:
            _, expense_error = _post_credit_advance_expense(
                conn,
                user,
                employee=emp,
                credit_id=credit_id,
                cr_date=cr_date,
                description=description,
                amount=raw_amount,
                payment_type=payment_type,
                transaction_id=transaction_id,
            )
            if expense_error:
                conn.rollback()
                return _json_error(expense_error)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "id": int(credit_id),
        "employee_id": emp_id_val,
        "date": cr_date,
        "description": description,
        "amount": amount_val,
        "transaction_type": txn_type,
    })


# ---------------------------------------------------------------------------
# Tips
# ---------------------------------------------------------------------------


@payroll_mobile_bp.route(
    "/api/mobile/payroll/tips",
    methods=["GET"],
    endpoint="mobile_payroll_tips",
)
def mobile_payroll_tips():
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "tips")
    if denied:
        return denied

    import app as app_module

    selected_company = (request.args.get("company") or app_module.DEFAULT_COMPANY).strip()
    if selected_company not in app_module.SALES_COMPANY_LOCATIONS:
        selected_company = app_module.DEFAULT_COMPANY
    location_filter = (request.args.get("location") or app_module.TIPS_FILTER_ALL).strip()
    if location_filter not in app_module.TIPS_FILTER_LOCATIONS:
        location_filter = app_module.TIPS_FILTER_ALL
    outlet_filter = (
        location_filter if location_filter in app_module.TIP_OUTLET_LOCATIONS else None
    )
    date_from = _parse_iso_date(request.args.get("date_from"))
    date_to = _parse_iso_date(request.args.get("date_to"))

    conn = get_db()
    try:
        bundle = app_module._load_tips_analytics_bundle(
            conn, selected_company, date_from, date_to, outlet_filter
        )
        recent_rows = app_module._load_tips_detail_entries(
            conn, selected_company, date_from, date_to, outlet_filter
        )
        picker = [
            {"id": int(r["id"]), "name": r["name"] or "", "emp_code": r["emp_code"] or ""}
            for r in app_module._active_employees_for_tips(conn)
        ]
    finally:
        conn.close()

    top_employees = list(bundle.get("employees") or [])[:10]
    recent = []
    for row in reversed(list(recent_rows or [])):
        recent.append({
            "id": row.get("id"),
            "date": row.get("sales_date") or "",
            "location": row.get("location") or "",
            "amount": _money(row.get("amount")),
            "description": row.get("description") or "",
            "employee_id": row.get("employee_id"),
            "employee_name": row.get("employee_name") or "",
            "emp_code": row.get("employee_code") or "",
        })
        if len(recent) >= 15:
            break

    return jsonify({
        "ok": True,
        "company": selected_company,
        "location": location_filter,
        "date_from": date_from.isoformat() if date_from else "",
        "date_to": date_to.isoformat() if date_to else "",
        "grand_total": _money(bundle.get("grand_total")),
        "hotel_total": _money(bundle.get("hotel_total")),
        "bar_total": _money(bundle.get("bar_total")),
        "restaurant_total": _money(bundle.get("restaurant_total")),
        "top_employees": top_employees,
        "recent": recent,
        "all_employees": picker,
        "locations": list(app_module.TIPS_FILTER_LOCATIONS),
    })


@payroll_mobile_bp.route(
    "/api/mobile/payroll/tips",
    methods=["POST"],
    endpoint="mobile_payroll_tips_add",
)
def mobile_payroll_tips_add():
    """Same validation as sales_update_add_tip, under the mobile payroll path."""
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "tips")
    if denied:
        return denied

    import app as app_module

    data = _request_json()
    company = data.get("company", app_module.DEFAULT_COMPANY)
    location = data.get("location", app_module.OUTLET_HOTEL)
    sales_date = str(data.get("date") or "").strip()
    description = str(data.get("description") or "").strip()
    amount = app_module.parse_money(data.get("amount"))
    try:
        employee_id = int(data.get("employee_id") or 0)
    except (TypeError, ValueError):
        employee_id = 0

    if location not in app_module.TIP_OUTLET_LOCATIONS:
        return _json_error("Tips can only be recorded for Hotel, Bar, or Restaurant.")
    if not sales_date or not _parse_iso_date(sales_date):
        return _json_error("A valid date is required.")
    lock_error = app_module._check_sales_date_lock(user, company, location, sales_date)
    if lock_error:
        return _json_error(lock_error, 403)
    if employee_id <= 0:
        return _json_error("Please select an employee.")
    if amount <= 0:
        return _json_error("Please enter a tip amount greater than 0.")

    conn = get_db()
    try:
        payroll_lock_error = app_module._check_payroll_month_date_lock(conn, sales_date)
        if payroll_lock_error:
            return _json_error(payroll_lock_error, 403, locked=True)
        employee = conn.execute(
            "SELECT id FROM employees WHERE id = ? AND status = 'active'",
            (employee_id,),
        ).fetchone()
        if not employee:
            return _json_error("Selected employee was not found.")
        cursor = conn.execute(
            """INSERT INTO sales_update_tips
               (company, location, sales_date, employee_id, amount, description)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (company, location, sales_date, employee_id, amount, description),
        )
        tip_id = cursor.lastrowid
        conn.commit()
        tip_total = app_module._sales_tip_total(conn, company, location, sales_date)
    finally:
        conn.close()

    return jsonify({
        "ok": True,
        "tip_id": tip_id,
        "tip_total": tip_total,
        "date": sales_date,
        "location": location,
        "employee_id": employee_id,
        "amount": amount,
    })


@payroll_mobile_bp.route(
    "/api/mobile/payroll/tips/incentive",
    methods=["GET"],
    endpoint="mobile_payroll_tips_incentive",
)
def mobile_payroll_tips_incentive():
    user, err = _require_login()
    if err:
        return err
    denied = _require_submodule(user, "tips")
    if denied:
        return denied

    import app as app_module
    from employee_payroll import _default_reporting_period, _parse_period_value

    selected_company = (request.args.get("company") or app_module.DEFAULT_COMPANY).strip() or app_module.DEFAULT_COMPANY
    if selected_company not in app_module.SALES_COMPANY_LOCATIONS:
        selected_company = app_module.DEFAULT_COMPANY
    default_year, default_month = _default_reporting_period()
    try:
        year, month = _parse_period_value(
            request.args.get("year", default_year),
            request.args.get("month", default_month),
        )
    except (TypeError, ValueError):
        year, month = default_year, default_month

    conn = get_db()
    try:
        payload = app_module._tips_incentive_payout_payload(conn, selected_company, year, month)
    finally:
        conn.close()
    if isinstance(payload, dict):
        payload = {**payload, "ok": True}
    return jsonify(payload)


def register_payroll_mobile(app):
    app.register_blueprint(payroll_mobile_bp)
