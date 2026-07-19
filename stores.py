"""Stores module — simple Bar/Kitchen indent-to-stock flow."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from flask import Blueprint, flash, redirect, render_template, request, url_for

from db import ensure_stores_schema, get_db
from workspace_access import user_can_access_stores_submodule

STORES_OUTLETS = (
    {"key": "bar", "label": "Bar"},
    {"key": "kitchen", "label": "Kitchen"},
)
OUTLET_KEYS = {item["key"] for item in STORES_OUTLETS}
DEFAULT_UNITS = ("kg", "pcs", "liter", "dozen", "bunch", "bottle", "case", "pack")

STATUS_LABELS = {
    "draft": "Draft",
    "pending": "Waiting approval",
    "approved": "Approved",
    "rejected": "Rejected",
    "open": "Open",
    "received": "Received in stock",
    "cancelled": "Cancelled",
}

PAGE_META = {
    "product_master": {
        "title": "Products",
        "subtitle": "Categories and products used when raising indents for Bar and Kitchen.",
        "step": "Master",
        "list_endpoint": "stores_product_master",
        "cta": "Add product",
        "cta_endpoint": "stores_product_master",
        "cta_args": {"focus": "form"},
        "show_outlet_tabs": False,
    },
    "indent": {
        "title": "Indent",
        "subtitle": "Ask for what the team needs. Keep it simple — item, quantity, unit.",
        "step": "1 · Indent",
        "list_endpoint": "stores_indent",
        "cta": "New Indent",
        "cta_endpoint": "stores_indent",
        "cta_args": {"focus": "form"},
    },
    "approvals": {
        "title": "Approvals",
        "subtitle": "Review waiting indents. Approve to buy, or reject with a short note.",
        "step": "2 · Approvals",
        "list_endpoint": "stores_approvals",
        "cta": None,
    },
    "purchase_requests": {
        "title": "Purchases",
        "subtitle": "Turn approved indents into purchases, then receive items into stock.",
        "step": "3 · Purchases",
        "list_endpoint": "stores_purchase_requests",
        "cta": None,
    },
    "stock": {
        "title": "Stock",
        "subtitle": "What is currently in the store for this outlet.",
        "step": "4 · Stock",
        "list_endpoint": "stores_stock",
        "cta": None,
    },
    "counter_transfer": {
        "title": "Transfers",
        "subtitle": "Move stock from store to the counter when the team needs it.",
        "step": "5 · Transfers",
        "list_endpoint": "stores_counter_transfer",
        "cta": "New transfer",
        "cta_endpoint": "stores_counter_transfer",
        "cta_args": {"focus": "form"},
    },
    "stock_verification": {
        "title": "Verification",
        "subtitle": "Count stock on a schedule. Overdue counts show as Due.",
        "step": "Verification",
        "list_endpoint": "stores_stock_verification",
        "cta": "Start verification",
        "cta_endpoint": "stores_stock_verification",
        "cta_args": {"focus": "form"},
    },
    "stock_issues": {
        "title": "Issues",
        "subtitle": "Reduce stock when goods are sold or used (invoice / issue).",
        "step": "6 · Issues",
        "list_endpoint": "stores_stock_issues",
        "cta": "New issue",
        "cta_endpoint": "stores_stock_issues",
        "cta_args": {"focus": "form"},
    },
}

stores_bp = Blueprint("stores", __name__)

_pop_auth_notice = None
_get_user = None


def _bind_helpers(pop_auth_notice, get_user):
    global _pop_auth_notice, _get_user
    _pop_auth_notice = pop_auth_notice
    _get_user = get_user


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _parse_outlet(raw: str | None) -> str:
    key = (raw or "bar").strip().lower()
    return key if key in OUTLET_KEYS else "bar"


def _outlet_label(outlet: str) -> str:
    for item in STORES_OUTLETS:
        if item["key"] == outlet:
            return item["label"]
    return outlet.title()


def _status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status.replace("_", " ").title())


def _next_doc_no(conn, table: str, column: str, prefix: str, outlet: str) -> str:
    day = date.today().strftime("%Y%m%d")
    outlet_code = outlet.upper()[:3]
    like = f"{prefix}-{outlet_code}-{day}-%"
    row = conn.execute(
        f"SELECT {column} AS doc_no FROM {table} WHERE {column} LIKE ? ORDER BY id DESC LIMIT 1",
        (like,),
    ).fetchone()
    seq = 1
    if row and row["doc_no"]:
        try:
            seq = int(str(row["doc_no"]).rsplit("-", 1)[-1]) + 1
        except ValueError:
            seq = 1
    return f"{prefix}-{outlet_code}-{day}-{seq:03d}"


def _parse_lines_from_form(form) -> list[dict[str, Any]]:
    names = form.getlist("item_name")
    qtys = form.getlist("quantity")
    units = form.getlist("unit")
    notes = form.getlist("line_notes")
    lines = []
    for idx, name in enumerate(names):
        item_name = (name or "").strip()
        if not item_name:
            continue
        try:
            qty = float(qtys[idx] if idx < len(qtys) else 0)
        except (TypeError, ValueError, IndexError):
            qty = 0
        if qty <= 0:
            continue
        unit = (units[idx] if idx < len(units) else "pcs") or "pcs"
        unit = unit.strip() or "pcs"
        note = (notes[idx] if idx < len(notes) else "") or ""
        lines.append({
            "item_name": item_name,
            "quantity": qty,
            "unit": unit,
            "notes": note.strip(),
        })
    return lines


def _adjust_stock(conn, *, outlet, item_name, unit, qty_delta, movement_type, ref_type, ref_id, notes, user_id):
    existing = conn.execute(
        """
        SELECT id, qty_on_hand FROM store_stock_items
        WHERE outlet = ? AND lower(item_name) = lower(?) AND lower(unit) = lower(?)
        """,
        (outlet, item_name, unit),
    ).fetchone()
    if existing:
        new_qty = float(existing["qty_on_hand"] or 0) + float(qty_delta)
        if new_qty < -0.0001:
            raise ValueError(f"Not enough stock for {item_name} ({unit}).")
        conn.execute(
            """
            UPDATE store_stock_items
            SET qty_on_hand = ?, item_name = ?, unit = ?, updated_at = ?
            WHERE id = ?
            """,
            (round(new_qty, 3), item_name, unit, _now(), existing["id"]),
        )
    else:
        if qty_delta < 0:
            raise ValueError(f"Not enough stock for {item_name} ({unit}).")
        conn.execute(
            """
            INSERT INTO store_stock_items (outlet, item_name, unit, qty_on_hand, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (outlet, item_name, unit, round(float(qty_delta), 3), _now()),
        )
    conn.execute(
        """
        INSERT INTO store_stock_movements
            (outlet, item_name, unit, qty_delta, movement_type, ref_type, ref_id, notes, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            outlet,
            item_name,
            unit,
            float(qty_delta),
            movement_type,
            ref_type,
            ref_id,
            notes or "",
            user_id,
            _now(),
        ),
    )


def _verification_due_info(conn, outlet: str) -> dict[str, Any]:
    settings = conn.execute(
        "SELECT verification_interval_days FROM store_settings WHERE outlet = ?",
        (outlet,),
    ).fetchone()
    interval = int(settings["verification_interval_days"] if settings else 7)
    last = conn.execute(
        """
        SELECT verified_at FROM store_stock_verifications
        WHERE outlet = ?
        ORDER BY verified_at DESC, id DESC
        LIMIT 1
        """,
        (outlet,),
    ).fetchone()
    last_at = last["verified_at"] if last else None
    due = True
    due_on = date.today()
    if last_at:
        try:
            last_dt = datetime.strptime(str(last_at)[:19], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            try:
                last_dt = datetime.strptime(str(last_at)[:10], "%Y-%m-%d")
            except ValueError:
                last_dt = None
        if last_dt:
            due_on = (last_dt + timedelta(days=interval)).date()
            due = date.today() >= due_on
    return {
        "interval_days": interval,
        "last_verified_at": last_at,
        "due_on": due_on.isoformat(),
        "is_due": due,
    }


def _load_product_catalog(conn):
    rows = conn.execute(
        """
        SELECT c.id AS category_id, c.name AS category_name, c.sort_order AS category_sort,
               p.id AS product_id, p.name AS product_name, p.default_unit, p.is_active, p.sort_order
        FROM store_product_categories c
        LEFT JOIN store_products p ON p.category_id = c.id AND p.is_active = 1
        WHERE c.is_active = 1
        ORDER BY c.sort_order, c.name, p.sort_order, p.name
        """
    ).fetchall()
    categories = []
    by_id = {}
    for row in rows:
        cat_id = row["category_id"]
        if cat_id not in by_id:
            node = {
                "id": cat_id,
                "name": row["category_name"],
                "products": [],
            }
            by_id[cat_id] = node
            categories.append(node)
        if row["product_id"]:
            by_id[cat_id]["products"].append({
                "id": row["product_id"],
                "name": row["product_name"],
                "default_unit": row["default_unit"],
            })
    return categories


def _load_flat_products(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.id, p.name, p.default_unit, p.category_id,
               c.name AS category_name, c.sort_order AS category_sort, p.sort_order
        FROM store_products p
        JOIN store_product_categories c ON c.id = p.category_id
        WHERE p.is_active = 1 AND c.is_active = 1
        ORDER BY c.sort_order, c.name, p.sort_order, p.name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _first_stores_endpoint(user) -> str | None:
    preferred = (
        "product_master",
        "indent",
        "approvals",
        "purchase_requests",
        "stock",
        "counter_transfer",
        "stock_verification",
        "stock_issues",
    )
    endpoint_map = {
        "product_master": "stores_product_master",
        "indent": "stores_indent",
        "approvals": "stores_approvals",
        "purchase_requests": "stores_purchase_requests",
        "stock": "stores_stock",
        "counter_transfer": "stores_counter_transfer",
        "stock_verification": "stores_stock_verification",
        "stock_issues": "stores_stock_issues",
    }
    for key in preferred:
        if user_can_access_stores_submodule(user, key):
            return endpoint_map[key]
    return None


def _page_render(page_key: str, **kwargs):
    user = _get_user() if _get_user else None
    outlet = _parse_outlet(kwargs.pop("outlet", None) or request.args.get("outlet"))
    meta = PAGE_META[page_key]
    cta_url = None
    if meta.get("cta_endpoint"):
        args = dict(meta.get("cta_args") or {})
        args["outlet"] = outlet
        cta_url = url_for(meta["cta_endpoint"], **args)
    kwargs.setdefault("auth_notice", _pop_auth_notice() if _pop_auth_notice else None)
    return render_template(
        "stores_page.html",
        de_nav_section="stores",
        de_nav_stores_view=page_key,
        stores_outlets=STORES_OUTLETS,
        selected_outlet=outlet,
        selected_outlet_label=_outlet_label(outlet),
        page_key=page_key,
        page_title=meta["title"],
        page_subtitle=meta["subtitle"],
        page_list_endpoint=meta["list_endpoint"],
        page_cta=meta.get("cta"),
        page_cta_url=cta_url,
        show_outlet_tabs=meta.get("show_outlet_tabs", True),
        status_label=_status_label,
        default_units=DEFAULT_UNITS,
        current_user=user,
        **kwargs,
    )


@stores_bp.route("/stores/product-master", methods=["GET", "POST"])
def stores_product_master():
    user = _get_user()
    edit_id = request.args.get("edit") or request.form.get("product_id") or ""
    try:
        edit_id_int = int(edit_id) if str(edit_id).strip() else 0
    except (TypeError, ValueError):
        edit_id_int = 0
    focus = (
        request.args.get("focus") == "form"
        or request.method == "POST"
        or bool(edit_id_int)
    )
    errors: list[str] = []
    form = {
        "product_id": "",
        "category_id": "",
        "name": "",
        "default_unit": "kg",
    }

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        if request.method == "POST":
            action = (request.form.get("action") or "save_product").strip()
            if action == "save_category":
                cat_name = (request.form.get("category_name") or "").strip()
                if not cat_name:
                    errors.append("Category name is required.")
                else:
                    exists = conn.execute(
                        "SELECT id FROM store_product_categories WHERE lower(name) = lower(?)",
                        (cat_name,),
                    ).fetchone()
                    if exists:
                        errors.append("That category already exists.")
                    else:
                        max_sort = conn.execute(
                            "SELECT COALESCE(MAX(sort_order), 0) AS m FROM store_product_categories"
                        ).fetchone()["m"]
                        conn.execute(
                            """
                            INSERT INTO store_product_categories (name, sort_order, is_active)
                            VALUES (?, ?, 1)
                            """,
                            (cat_name, int(max_sort) + 10),
                        )
                        conn.commit()
                        flash("Category added.", "ok")
                        return redirect(url_for("stores_product_master"))
            else:
                form["name"] = (request.form.get("name") or "").strip()
                form["default_unit"] = (request.form.get("default_unit") or "kg").strip() or "kg"
                form["category_id"] = (request.form.get("category_id") or "").strip()
                form["product_id"] = (request.form.get("product_id") or "").strip()
                try:
                    category_id = int(form["category_id"])
                except (TypeError, ValueError):
                    category_id = 0
                try:
                    product_id = int(form["product_id"]) if form["product_id"] else 0
                except (TypeError, ValueError):
                    product_id = 0
                if not form["name"]:
                    errors.append("Product name is required.")
                if not category_id:
                    errors.append("Choose a category.")
                if not errors:
                    exists = conn.execute(
                        """
                        SELECT id FROM store_products
                        WHERE category_id = ? AND lower(name) = lower(?) AND is_active = 1
                          AND (? = 0 OR id != ?)
                        """,
                        (category_id, form["name"], product_id, product_id),
                    ).fetchone()
                    if exists:
                        errors.append("That product already exists in this category.")
                    elif product_id:
                        row = conn.execute(
                            "SELECT id FROM store_products WHERE id = ? AND is_active = 1",
                            (product_id,),
                        ).fetchone()
                        if not row:
                            errors.append("Product not found.")
                        else:
                            conn.execute(
                                """
                                UPDATE store_products
                                SET category_id = ?, name = ?, default_unit = ?, updated_at = ?
                                WHERE id = ?
                                """,
                                (
                                    category_id,
                                    form["name"],
                                    form["default_unit"],
                                    _now(),
                                    product_id,
                                ),
                            )
                            conn.commit()
                            flash("Product updated.", "ok")
                            return redirect(url_for("stores_product_master"))
                    else:
                        max_sort = conn.execute(
                            """
                            SELECT COALESCE(MAX(sort_order), 0) AS m
                            FROM store_products WHERE category_id = ?
                            """,
                            (category_id,),
                        ).fetchone()["m"]
                        conn.execute(
                            """
                            INSERT INTO store_products
                                (category_id, name, default_unit, is_active, sort_order, updated_at)
                            VALUES (?, ?, ?, 1, ?, ?)
                            """,
                            (
                                category_id,
                                form["name"],
                                form["default_unit"],
                                int(max_sort) + 10,
                                _now(),
                            ),
                        )
                        conn.commit()
                        flash("Product added to master.", "ok")
                        return redirect(url_for("stores_product_master"))

        if edit_id_int and request.method == "GET":
            row = conn.execute(
                """
                SELECT id, category_id, name, default_unit
                FROM store_products
                WHERE id = ? AND is_active = 1
                """,
                (edit_id_int,),
            ).fetchone()
            if row:
                form["product_id"] = str(row["id"])
                form["category_id"] = str(row["category_id"])
                form["name"] = row["name"]
                form["default_unit"] = row["default_unit"] or "kg"
            else:
                flash("Product not found.", "error")
                return redirect(url_for("stores_product_master"))

        catalog = _load_product_catalog(conn)
        products = _load_flat_products(conn)
        categories = conn.execute(
            """
            SELECT id, name FROM store_product_categories
            WHERE is_active = 1
            ORDER BY sort_order, name
            """
        ).fetchall()
        product_count = len(products)
    finally:
        conn.close()

    return _page_render(
        "product_master",
        catalog=catalog,
        products=products,
        categories=[dict(row) for row in categories],
        product_count=product_count,
        show_form=focus or bool(errors),
        form=form,
        errors=errors,
        editing=bool(form.get("product_id")),
    )


@stores_bp.route("/stores/product-master/<int:product_id>/delete", methods=["GET", "POST"])
def stores_product_delete(product_id: int):
    _get_user()
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        row = conn.execute(
            "SELECT id, name FROM store_products WHERE id = ? AND is_active = 1",
            (product_id,),
        ).fetchone()
        if not row:
            flash("Product not found.", "error")
        else:
            conn.execute(
                """
                UPDATE store_products
                SET is_active = 0, updated_at = ?
                WHERE id = ?
                """,
                (_now(), product_id),
            )
            conn.commit()
            flash(f"Deleted {row['name']}.", "ok")
    finally:
        conn.close()
    return redirect(url_for("stores_product_master"))


@stores_bp.route("/stores")
def stores():
    user = _get_user()
    endpoint = _first_stores_endpoint(user)
    if not endpoint:
        flash("No Stores pages are available for this account.", "error")
        return redirect(url_for("home"))
    return redirect(url_for(endpoint, outlet=request.args.get("outlet") or "bar"))


@stores_bp.route("/stores/indent", methods=["GET", "POST"])
def stores_indent():
    outlet = _parse_outlet(request.args.get("outlet") or request.form.get("outlet"))
    user = _get_user()
    focus = request.args.get("focus") == "form" or request.method == "POST"
    errors: list[str] = []
    form = {
        "notes": "",
        "lines": [{"item_name": "", "quantity": "", "unit": "kg", "notes": ""}],
    }

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        if request.method == "POST":
            form["notes"] = (request.form.get("notes") or "").strip()
            lines = _parse_lines_from_form(request.form)
            form["lines"] = lines or [{"item_name": "", "quantity": "", "unit": "kg", "notes": ""}]
            action = (request.form.get("action") or "save").strip()
            if not lines:
                errors.append("Add at least one item with a quantity.")
            if not errors:
                indent_no = _next_doc_no(conn, "store_indents", "indent_no", "IND", outlet)
                status = "pending" if action == "submit" else "draft"
                cur = conn.execute(
                    """
                    INSERT INTO store_indents
                        (outlet, indent_no, status, notes, created_by, created_at, submitted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outlet,
                        indent_no,
                        status,
                        form["notes"],
                        user["id"] if user else None,
                        _now(),
                        _now() if status == "pending" else None,
                    ),
                )
                indent_id = cur.lastrowid
                for line in lines:
                    conn.execute(
                        """
                        INSERT INTO store_indent_lines (indent_id, item_name, quantity, unit, notes)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (indent_id, line["item_name"], line["quantity"], line["unit"], line["notes"]),
                    )
                conn.commit()
                msg = "Indent sent for approval." if status == "pending" else "Indent saved as draft."
                flash(msg, "ok")
                return redirect(url_for("stores_indent", outlet=outlet))

        catalog = _load_product_catalog(conn)
        rows = conn.execute(
            """
            SELECT i.*, u.full_name AS created_by_name,
                   (SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id) AS line_count,
                   (SELECT COALESCE(SUM(l.quantity), 0) FROM store_indent_lines l WHERE l.indent_id = i.id) AS total_qty
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            WHERE i.outlet = ?
            ORDER BY i.created_at DESC, i.id DESC
            """,
            (outlet,),
        ).fetchall()
        indents = [dict(row) for row in rows]
    finally:
        conn.close()

    return _page_render(
        "indent",
        outlet=outlet,
        indents=indents,
        product_catalog=catalog,
        show_form=focus or bool(errors),
        form=form,
        errors=errors,
    )


@stores_bp.route("/stores/indent/<int:indent_id>")
def stores_indent_detail(indent_id: int):
    outlet = _parse_outlet(request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute(
            """
            SELECT i.*, u.full_name AS created_by_name, d.full_name AS decided_by_name
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            LEFT JOIN users d ON d.id = i.decided_by
            WHERE i.id = ?
            """,
            (indent_id,),
        ).fetchone()
        if not indent:
            flash("Indent not found.", "error")
            return redirect(url_for("stores_indent", outlet=outlet))
        outlet = indent["outlet"]
        lines = conn.execute(
            "SELECT * FROM store_indent_lines WHERE indent_id = ? ORDER BY id",
            (indent_id,),
        ).fetchall()
    finally:
        conn.close()
    return _page_render(
        "indent",
        outlet=outlet,
        indents=[],
        show_form=False,
        detail=dict(indent),
        detail_lines=[dict(line) for line in lines],
        form=None,
        errors=[],
    )


@stores_bp.route("/stores/indent/<int:indent_id>/submit", methods=["POST"])
def stores_indent_submit(indent_id: int):
    outlet = _parse_outlet(request.form.get("outlet") or request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute("SELECT * FROM store_indents WHERE id = ?", (indent_id,)).fetchone()
        if not indent:
            flash("Indent not found.", "error")
            return redirect(url_for("stores_indent", outlet=outlet))
        outlet = indent["outlet"]
        if indent["status"] != "draft":
            flash("Only draft indents can be sent for approval.", "error")
            return redirect(url_for("stores_indent", outlet=outlet))
        line_count = conn.execute(
            "SELECT COUNT(*) AS c FROM store_indent_lines WHERE indent_id = ?",
            (indent_id,),
        ).fetchone()["c"]
        if not line_count:
            flash("Add items before sending for approval.", "error")
            return redirect(url_for("stores_indent_detail", indent_id=indent_id, outlet=outlet))
        conn.execute(
            "UPDATE store_indents SET status = 'pending', submitted_at = ? WHERE id = ?",
            (_now(), indent_id),
        )
        conn.commit()
    finally:
        conn.close()
    flash("Indent sent for approval.", "ok")
    return redirect(url_for("stores_indent", outlet=outlet))


@stores_bp.route("/stores/approvals")
def stores_approvals():
    outlet = _parse_outlet(request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        pending = conn.execute(
            """
            SELECT i.*, u.full_name AS created_by_name,
                   (SELECT COUNT(*) FROM store_indent_lines l WHERE l.indent_id = i.id) AS line_count
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            WHERE i.outlet = ? AND i.status = 'pending'
            ORDER BY i.submitted_at ASC, i.id ASC
            """,
            (outlet,),
        ).fetchall()
        recent = conn.execute(
            """
            SELECT i.*, u.full_name AS created_by_name, d.full_name AS decided_by_name
            FROM store_indents i
            LEFT JOIN users u ON u.id = i.created_by
            LEFT JOIN users d ON d.id = i.decided_by
            WHERE i.outlet = ? AND i.status IN ('approved', 'rejected')
            ORDER BY i.decided_at DESC, i.id DESC
            LIMIT 20
            """,
            (outlet,),
        ).fetchall()
    finally:
        conn.close()
    return _page_render(
        "approvals",
        outlet=outlet,
        pending=[dict(row) for row in pending],
        recent=[dict(row) for row in recent],
    )


@stores_bp.route("/stores/indent/<int:indent_id>/decide", methods=["POST"])
def stores_indent_decide(indent_id: int):
    user = _get_user()
    decision = (request.form.get("decision") or "").strip().lower()
    note = (request.form.get("decision_note") or "").strip()
    outlet = _parse_outlet(request.form.get("outlet"))
    if decision not in {"approved", "rejected"}:
        flash("Choose approve or reject.", "error")
        return redirect(url_for("stores_approvals", outlet=outlet))
    if decision == "rejected" and not note:
        flash("Add a short reason when rejecting.", "error")
        return redirect(url_for("stores_approvals", outlet=outlet))

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        indent = conn.execute("SELECT * FROM store_indents WHERE id = ?", (indent_id,)).fetchone()
        if not indent or indent["status"] != "pending":
            flash("This indent is not waiting for approval.", "error")
            return redirect(url_for("stores_approvals", outlet=outlet))
        outlet = indent["outlet"]
        conn.execute(
            """
            UPDATE store_indents
            SET status = ?, decided_by = ?, decided_at = ?, decision_note = ?
            WHERE id = ?
            """,
            (decision, user["id"] if user else None, _now(), note, indent_id),
        )
        conn.commit()
    finally:
        conn.close()
    flash("Indent approved." if decision == "approved" else "Indent rejected.", "ok")
    return redirect(url_for("stores_approvals", outlet=outlet))


@stores_bp.route("/stores/purchase-requests", methods=["GET", "POST"])
def stores_purchase_requests():
    outlet = _parse_outlet(request.args.get("outlet") or request.form.get("outlet"))
    user = _get_user()

    if request.method == "POST" and request.form.get("action") == "create_from_indent":
        try:
            indent_id = int(request.form.get("indent_id") or 0)
        except (TypeError, ValueError):
            indent_id = 0
        conn = get_db()
        try:
            ensure_stores_schema(conn)
            indent = conn.execute(
                "SELECT * FROM store_indents WHERE id = ? AND status = 'approved'",
                (indent_id,),
            ).fetchone()
            if not indent:
                flash("Select an approved indent.", "error")
                return redirect(url_for("stores_purchase_requests", outlet=outlet))
            outlet = indent["outlet"]
            existing = conn.execute(
                "SELECT id FROM store_purchase_requests WHERE indent_id = ?",
                (indent_id,),
            ).fetchone()
            if existing:
                flash("A purchase request already exists for this indent.", "error")
                return redirect(url_for("stores_purchase_requests", outlet=outlet))
            lines = conn.execute(
                "SELECT * FROM store_indent_lines WHERE indent_id = ? ORDER BY id",
                (indent_id,),
            ).fetchall()
            if not lines:
                flash("This indent has no items.", "error")
                return redirect(url_for("stores_purchase_requests", outlet=outlet))
            pr_no = _next_doc_no(conn, "store_purchase_requests", "pr_no", "PR", outlet)
            cur = conn.execute(
                """
                INSERT INTO store_purchase_requests
                    (indent_id, outlet, pr_no, status, notes, created_by, created_at)
                VALUES (?, ?, ?, 'open', ?, ?, ?)
                """,
                (
                    indent_id,
                    outlet,
                    pr_no,
                    (request.form.get("notes") or "").strip(),
                    user["id"] if user else None,
                    _now(),
                ),
            )
            pr_id = cur.lastrowid
            for line in lines:
                conn.execute(
                    """
                    INSERT INTO store_purchase_request_lines (pr_id, item_name, quantity, unit, notes)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (pr_id, line["item_name"], line["quantity"], line["unit"], line["notes"] or ""),
                )
            conn.commit()
        finally:
            conn.close()
        flash("Purchase request created.", "ok")
        return redirect(url_for("stores_purchase_requests", outlet=outlet))

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        approved = conn.execute(
            """
            SELECT i.*,
                   (SELECT COUNT(*) FROM store_purchase_requests p WHERE p.indent_id = i.id) AS pr_count
            FROM store_indents i
            WHERE i.outlet = ? AND i.status = 'approved'
            ORDER BY i.decided_at DESC, i.id DESC
            """,
            (outlet,),
        ).fetchall()
        prs = conn.execute(
            """
            SELECT p.*, i.indent_no,
                   (SELECT COUNT(*) FROM store_purchase_request_lines l WHERE l.pr_id = p.id) AS line_count
            FROM store_purchase_requests p
            LEFT JOIN store_indents i ON i.id = p.indent_id
            WHERE p.outlet = ?
            ORDER BY p.created_at DESC, p.id DESC
            """,
            (outlet,),
        ).fetchall()
    finally:
        conn.close()
    return _page_render(
        "purchase_requests",
        outlet=outlet,
        approved_indents=[dict(row) for row in approved if not row["pr_count"]],
        purchase_requests=[dict(row) for row in prs],
    )


@stores_bp.route("/stores/purchase-requests/<int:pr_id>")
def stores_pr_detail(pr_id: int):
    outlet = _parse_outlet(request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        pr = conn.execute(
            """
            SELECT p.*, i.indent_no
            FROM store_purchase_requests p
            LEFT JOIN store_indents i ON i.id = p.indent_id
            WHERE p.id = ?
            """,
            (pr_id,),
        ).fetchone()
        if not pr:
            flash("Purchase request not found.", "error")
            return redirect(url_for("stores_purchase_requests", outlet=outlet))
        outlet = pr["outlet"]
        lines = conn.execute(
            "SELECT * FROM store_purchase_request_lines WHERE pr_id = ? ORDER BY id",
            (pr_id,),
        ).fetchall()
    finally:
        conn.close()
    return _page_render(
        "purchase_requests",
        outlet=outlet,
        approved_indents=[],
        purchase_requests=[],
        detail=dict(pr),
        detail_lines=[dict(line) for line in lines],
    )


@stores_bp.route("/stores/purchase-requests/<int:pr_id>/receive", methods=["POST"])
def stores_pr_receive(pr_id: int):
    user = _get_user()
    outlet = _parse_outlet(request.form.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        pr = conn.execute("SELECT * FROM store_purchase_requests WHERE id = ?", (pr_id,)).fetchone()
        if not pr:
            flash("Purchase request not found.", "error")
            return redirect(url_for("stores_purchase_requests", outlet=outlet))
        outlet = pr["outlet"]
        if pr["status"] != "open":
            flash("This purchase request was already received.", "error")
            return redirect(url_for("stores_purchase_requests", outlet=outlet))
        lines = conn.execute(
            "SELECT * FROM store_purchase_request_lines WHERE pr_id = ? ORDER BY id",
            (pr_id,),
        ).fetchall()
        for line in lines:
            _adjust_stock(
                conn,
                outlet=outlet,
                item_name=line["item_name"],
                unit=line["unit"],
                qty_delta=float(line["quantity"]),
                movement_type="receive",
                ref_type="purchase_request",
                ref_id=pr_id,
                notes=f"Received from {pr['pr_no']}",
                user_id=user["id"] if user else None,
            )
        conn.execute(
            "UPDATE store_purchase_requests SET status = 'received', received_at = ? WHERE id = ?",
            (_now(), pr_id),
        )
        conn.commit()
    except ValueError as exc:
        conn.rollback()
        flash(str(exc), "error")
        return redirect(url_for("stores_purchase_requests", outlet=outlet))
    finally:
        conn.close()
    flash("Items received into stock.", "ok")
    return redirect(url_for("stores_stock", outlet=outlet))


@stores_bp.route("/stores/stock")
def stores_stock():
    outlet = _parse_outlet(request.args.get("outlet"))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        items = conn.execute(
            """
            SELECT * FROM store_stock_items
            WHERE outlet = ?
            ORDER BY lower(item_name), lower(unit)
            """,
            (outlet,),
        ).fetchall()
        movements = conn.execute(
            """
            SELECT m.*, u.full_name AS created_by_name
            FROM store_stock_movements m
            LEFT JOIN users u ON u.id = m.created_by
            WHERE m.outlet = ?
            ORDER BY m.created_at DESC, m.id DESC
            LIMIT 25
            """,
            (outlet,),
        ).fetchall()
        due = _verification_due_info(conn, outlet)
    finally:
        conn.close()
    return _page_render(
        "stock",
        outlet=outlet,
        stock_items=[dict(row) for row in items],
        movements=[dict(row) for row in movements],
        verification_due=due,
    )


@stores_bp.route("/stores/counter-transfer", methods=["GET", "POST"])
def stores_counter_transfer():
    outlet = _parse_outlet(request.args.get("outlet") or request.form.get("outlet"))
    user = _get_user()
    focus = request.args.get("focus") == "form" or request.method == "POST"
    errors: list[str] = []
    form = {
        "notes": "",
        "lines": [{"item_name": "", "quantity": "", "unit": "pcs"}],
    }

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        stock_options = conn.execute(
            """
            SELECT item_name, unit, qty_on_hand FROM store_stock_items
            WHERE outlet = ? AND qty_on_hand > 0
            ORDER BY lower(item_name)
            """,
            (outlet,),
        ).fetchall()

        if request.method == "POST":
            form["notes"] = (request.form.get("notes") or "").strip()
            lines = _parse_lines_from_form(request.form)
            form["lines"] = lines or [{"item_name": "", "quantity": "", "unit": "pcs"}]
            if not lines:
                errors.append("Add at least one item to transfer.")
            if not errors:
                try:
                    transfer_no = _next_doc_no(
                        conn, "store_counter_transfers", "transfer_no", "CT", outlet
                    )
                    cur = conn.execute(
                        """
                        INSERT INTO store_counter_transfers
                            (outlet, transfer_no, notes, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            outlet,
                            transfer_no,
                            form["notes"],
                            user["id"] if user else None,
                            _now(),
                        ),
                    )
                    transfer_id = cur.lastrowid
                    for line in lines:
                        conn.execute(
                            """
                            INSERT INTO store_counter_transfer_lines
                                (transfer_id, item_name, unit, quantity)
                            VALUES (?, ?, ?, ?)
                            """,
                            (transfer_id, line["item_name"], line["unit"], line["quantity"]),
                        )
                        _adjust_stock(
                            conn,
                            outlet=outlet,
                            item_name=line["item_name"],
                            unit=line["unit"],
                            qty_delta=-float(line["quantity"]),
                            movement_type="transfer_out",
                            ref_type="counter_transfer",
                            ref_id=transfer_id,
                            notes=f"Counter transfer {transfer_no}",
                            user_id=user["id"] if user else None,
                        )
                    conn.commit()
                    flash("Counter transfer saved. Store stock reduced.", "ok")
                    return redirect(url_for("stores_counter_transfer", outlet=outlet))
                except ValueError as exc:
                    conn.rollback()
                    errors.append(str(exc))

        transfers = conn.execute(
            """
            SELECT t.*,
                   (SELECT COUNT(*) FROM store_counter_transfer_lines l WHERE l.transfer_id = t.id) AS line_count,
                   (SELECT COALESCE(SUM(l.quantity), 0) FROM store_counter_transfer_lines l WHERE l.transfer_id = t.id) AS total_qty
            FROM store_counter_transfers t
            WHERE t.outlet = ?
            ORDER BY t.created_at DESC, t.id DESC
            """,
            (outlet,),
        ).fetchall()
    finally:
        conn.close()

    return _page_render(
        "counter_transfer",
        outlet=outlet,
        transfers=[dict(row) for row in transfers],
        stock_options=[dict(row) for row in stock_options],
        show_form=focus,
        form=form,
        errors=errors,
    )


@stores_bp.route("/stores/stock-issues", methods=["GET", "POST"])
def stores_stock_issues():
    outlet = _parse_outlet(request.args.get("outlet") or request.form.get("outlet"))
    user = _get_user()
    focus = request.args.get("focus") == "form" or request.method == "POST"
    errors: list[str] = []
    form = {
        "invoice_ref": "",
        "notes": "",
        "lines": [{"item_name": "", "quantity": "", "unit": "pcs"}],
    }

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        stock_options = conn.execute(
            """
            SELECT item_name, unit, qty_on_hand FROM store_stock_items
            WHERE outlet = ? AND qty_on_hand > 0
            ORDER BY lower(item_name)
            """,
            (outlet,),
        ).fetchall()

        if request.method == "POST":
            form["invoice_ref"] = (request.form.get("invoice_ref") or "").strip()
            form["notes"] = (request.form.get("notes") or "").strip()
            lines = _parse_lines_from_form(request.form)
            form["lines"] = lines or [{"item_name": "", "quantity": "", "unit": "pcs"}]
            if not lines:
                errors.append("Add at least one item to issue.")
            if not errors:
                try:
                    issue_no = _next_doc_no(conn, "store_stock_issues", "issue_no", "ISS", outlet)
                    cur = conn.execute(
                        """
                        INSERT INTO store_stock_issues
                            (outlet, issue_no, invoice_ref, notes, created_by, created_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            outlet,
                            issue_no,
                            form["invoice_ref"],
                            form["notes"],
                            user["id"] if user else None,
                            _now(),
                        ),
                    )
                    issue_id = cur.lastrowid
                    for line in lines:
                        conn.execute(
                            """
                            INSERT INTO store_stock_issue_lines
                                (issue_id, item_name, unit, quantity)
                            VALUES (?, ?, ?, ?)
                            """,
                            (issue_id, line["item_name"], line["unit"], line["quantity"]),
                        )
                        _adjust_stock(
                            conn,
                            outlet=outlet,
                            item_name=line["item_name"],
                            unit=line["unit"],
                            qty_delta=-float(line["quantity"]),
                            movement_type="issue",
                            ref_type="stock_issue",
                            ref_id=issue_id,
                            notes=form["invoice_ref"] or f"Issue {issue_no}",
                            user_id=user["id"] if user else None,
                        )
                    conn.commit()
                    flash("Stock reduced for this issue.", "ok")
                    return redirect(url_for("stores_stock_issues", outlet=outlet))
                except ValueError as exc:
                    conn.rollback()
                    errors.append(str(exc))

        issues = conn.execute(
            """
            SELECT s.*,
                   (SELECT COUNT(*) FROM store_stock_issue_lines l WHERE l.issue_id = s.id) AS line_count,
                   (SELECT COALESCE(SUM(l.quantity), 0) FROM store_stock_issue_lines l WHERE l.issue_id = s.id) AS total_qty
            FROM store_stock_issues s
            WHERE s.outlet = ?
            ORDER BY s.created_at DESC, s.id DESC
            """,
            (outlet,),
        ).fetchall()
    finally:
        conn.close()

    return _page_render(
        "stock_issues",
        outlet=outlet,
        issues=[dict(row) for row in issues],
        stock_options=[dict(row) for row in stock_options],
        show_form=focus,
        form=form,
        errors=errors,
    )


@stores_bp.route("/stores/stock-verification", methods=["GET", "POST"])
def stores_stock_verification():
    outlet = _parse_outlet(request.args.get("outlet") or request.form.get("outlet"))
    user = _get_user()
    focus = request.args.get("focus") == "form"
    errors: list[str] = []

    conn = get_db()
    try:
        ensure_stores_schema(conn)
        due = _verification_due_info(conn, outlet)
        items = conn.execute(
            """
            SELECT * FROM store_stock_items
            WHERE outlet = ?
            ORDER BY lower(item_name)
            """,
            (outlet,),
        ).fetchall()

        if request.method == "POST" and request.form.get("action") == "save_verification":
            notes = (request.form.get("notes") or "").strip()
            if not items:
                errors.append("No stock items to verify yet.")
            else:
                cur = conn.execute(
                    """
                    INSERT INTO store_stock_verifications
                        (outlet, verified_at, verified_by, notes)
                    VALUES (?, ?, ?, ?)
                    """,
                    (outlet, _now(), user["id"] if user else None, notes),
                )
                verification_id = cur.lastrowid
                for item in items:
                    key = f"count_{item['id']}"
                    raw = request.form.get(key)
                    try:
                        counted = float(raw) if raw not in (None, "") else float(item["qty_on_hand"])
                    except (TypeError, ValueError):
                        counted = float(item["qty_on_hand"])
                    system_qty = float(item["qty_on_hand"])
                    conn.execute(
                        """
                        INSERT INTO store_stock_verification_lines
                            (verification_id, item_name, unit, system_qty, counted_qty)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            verification_id,
                            item["item_name"],
                            item["unit"],
                            system_qty,
                            counted,
                        ),
                    )
                    variance = counted - system_qty
                    if abs(variance) > 0.0001:
                        _adjust_stock(
                            conn,
                            outlet=outlet,
                            item_name=item["item_name"],
                            unit=item["unit"],
                            qty_delta=variance,
                            movement_type="verification_adjust",
                            ref_type="stock_verification",
                            ref_id=verification_id,
                            notes="Stock verification adjustment",
                            user_id=user["id"] if user else None,
                        )
                conn.commit()
                flash("Stock verification saved.", "ok")
                return redirect(url_for("stores_stock_verification", outlet=outlet))

        history = conn.execute(
            """
            SELECT v.*, u.full_name AS verified_by_name
            FROM store_stock_verifications v
            LEFT JOIN users u ON u.id = v.verified_by
            WHERE v.outlet = ?
            ORDER BY v.verified_at DESC, v.id DESC
            LIMIT 15
            """,
            (outlet,),
        ).fetchall()
    finally:
        conn.close()

    return _page_render(
        "stock_verification",
        outlet=outlet,
        verification_due=due,
        stock_items=[dict(row) for row in items],
        history=[dict(row) for row in history],
        show_form=focus or bool(errors),
        errors=errors,
    )


@stores_bp.route("/stores/stock-verification/settings", methods=["POST"])
def stores_verification_settings():
    outlet = _parse_outlet(request.form.get("outlet"))
    try:
        days = int(request.form.get("verification_interval_days") or 7)
    except (TypeError, ValueError):
        days = 7
    days = max(1, min(days, 90))
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        conn.execute(
            """
            INSERT INTO store_settings (outlet, verification_interval_days, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(outlet) DO UPDATE SET
                verification_interval_days = excluded.verification_interval_days,
                updated_at = excluded.updated_at
            """,
            (outlet, days, _now()),
        )
        conn.commit()
    finally:
        conn.close()
    flash(f"Verification every {days} day(s) saved.", "ok")
    return redirect(url_for("stores_stock_verification", outlet=outlet))


def register_stores(app, *, pop_auth_notice, get_user):
    _bind_helpers(pop_auth_notice, get_user)
    app.register_blueprint(stores_bp)
    for rule in list(app.url_map.iter_rules()):
        if not rule.endpoint.startswith("stores."):
            continue
        bare = rule.endpoint.split(".", 1)[1]
        if bare in app.view_functions:
            continue
        app.add_url_rule(
            rule.rule,
            endpoint=bare,
            view_func=app.view_functions[rule.endpoint],
            methods=rule.methods,
        )
