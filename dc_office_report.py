"""DC Office bar monthly stock register — Opening Stock (Bottles + Pegs 30ML)."""

from __future__ import annotations

import calendar
import math
import re
from datetime import date
from io import BytesIO
from pathlib import Path
from typing import Any

from flask import render_template, request, send_file, url_for
from openpyxl import load_workbook

from db import (
    _normalize_pos_menu_unit,
    _pos_money,
    ensure_stores_schema,
    get_db,
    get_pos_tax_rates,
    list_pos_unit_insights_raw,
)
from reports import report_export_month_filename

DC_OFFICE_TITLE = "DC Office"
DC_OFFICE_EXPORT_TITLE = "DC Office"
DEFAULT_BOTTLE_ML = 750.0
DEFAULT_PEG_ML = 30.0
# July DC Office register: page 1 spirits (mL→bottles/pegs), page 2 beer (bottle/can as bottles).
HEADER_TITLE_ROW = 4
SPIRITS_DATA_START = 7
SPIRITS_DATA_END = 63  # rows before blank spacer / beer headers
BEER_SECTION_LABEL_ROW = 68
BEER_DATA_START = 69

_TEMPLATE_PATH = (
    Path(__file__).resolve().parent / "templates" / "reports" / "dc_office_report_template.xlsx"
)

_MONTH_TOKEN_RE = re.compile(
    r"\b("
    + "|".join(calendar.month_name[1:])
    + r")\s+(\d{4})\b",
    re.IGNORECASE,
)


def ml_to_bottles_and_pegs(
    total_ml: float,
    *,
    bottle_ml: float = DEFAULT_BOTTLE_ML,
    peg_ml: float = DEFAULT_PEG_ML,
) -> tuple[int, int]:
    """Split liquid stock into whole bottles and leftover 30ml pegs."""
    try:
        ml = float(total_ml)
    except (TypeError, ValueError):
        return 0, 0
    if ml != ml or ml <= 0:
        return 0, 0
    try:
        bml = float(bottle_ml) if bottle_ml else DEFAULT_BOTTLE_ML
    except (TypeError, ValueError):
        bml = DEFAULT_BOTTLE_ML
    if bml <= 0 or bml != bml:
        bml = DEFAULT_BOTTLE_ML
    try:
        pml = float(peg_ml) if peg_ml else DEFAULT_PEG_ML
    except (TypeError, ValueError):
        pml = DEFAULT_PEG_ML
    if pml <= 0 or pml != pml:
        pml = DEFAULT_PEG_ML
    bottles = int(math.floor(ml / bml))
    rem = ml - (bottles * bml)
    pegs = int(math.floor(rem / pml))
    return bottles, pegs


def resolve_bottle_ml(variants: list[dict[str, Any]] | None, *, default: float = DEFAULT_BOTTLE_ML) -> float:
    """Pick pack size in base mL (largest pack with qty_in_base >= 100)."""
    best: float | None = None
    for variant in variants or []:
        try:
            qty = float(variant.get("qty_in_base") or 0)
        except (TypeError, ValueError):
            continue
        if qty != qty or qty < 100:
            continue
        if best is None or qty > best:
            best = qty
    return float(best if best is not None else default)


def _normalize_item_name(name: str) -> str:
    return " ".join(str(name or "").strip().lower().split())


def _stock_unit_key(unit: str) -> str:
    return _normalize_pos_menu_unit(unit)


def _load_bar_products(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT p.id, p.name, COALESCE(p.default_unit, '') AS default_unit,
               COALESCE(c.name, '') AS category_name
        FROM store_products p
        LEFT JOIN store_product_categories c ON c.id = p.category_id
        WHERE p.is_active = 1
          AND lower(trim(coalesce(p.outlet, ''))) IN ('bar', 'both')
        ORDER BY lower(trim(p.name)) ASC, p.id ASC
        """
    ).fetchall()
    products: list[dict[str, Any]] = []
    for row in rows:
        pid = int(row["id"])
        variants = conn.execute(
            """
            SELECT label, qty_in_base
            FROM store_product_variants
            WHERE product_id = ?
            ORDER BY sort_order ASC, id ASC
            """,
            (pid,),
        ).fetchall()
        products.append(
            {
                "id": pid,
                "name": (row["name"] or "").strip(),
                "default_unit": (row["default_unit"] or "").strip() or "pcs",
                "category_name": (row["category_name"] or "").strip(),
                "variants": [
                    {
                        "label": (v["label"] or "").strip(),
                        "qty_in_base": float(v["qty_in_base"] or 0),
                    }
                    for v in variants
                ],
            }
        )
    return products


def _sum_bar_counter_warehouse_qty(conn) -> dict[tuple[str, str], float]:
    """Map (normalized name, unit key) → on-hand from bar **counter + warehouse**.

    Both places are always summed. Callers convert mixed units into the product
    reporting base via ``_combined_on_hand_for_product``.
    """
    rows = conn.execute(
        """
        SELECT item_name, unit, COALESCE(SUM(qty_on_hand), 0) AS qty
        FROM store_stock_items
        WHERE lower(trim(coalesce(outlet, ''))) = 'bar'
          AND lower(trim(coalesce(place, ''))) IN ('counter', 'warehouse')
        GROUP BY item_name, unit
        """
    ).fetchall()
    totals: dict[tuple[str, str], float] = {}
    for row in rows:
        key = (_normalize_item_name(row["item_name"]), _stock_unit_key(row["unit"]))
        try:
            qty = float(row["qty"] or 0)
        except (TypeError, ValueError):
            qty = 0.0
        totals[key] = totals.get(key, 0.0) + qty
    return totals


_BOTTLE_PAGE_CATEGORIES = frozenset({"beer", "alcopop"})


def _is_bottle_page_product(product: dict[str, Any]) -> bool:
    """Second page: Product Master categories Beer and Alcopop (sold as bottles)."""
    cat = _normalize_item_name(product.get("category_name") or "")
    if cat in _BOTTLE_PAGE_CATEGORIES:
        return True
    # Tolerate spelling variants (e.g. "Alco Pop", "Beer Can").
    return "alcopop" in cat or "alco pop" in cat or cat == "beer" or cat.startswith("beer ")


def _combined_on_hand_for_product(
    product: dict[str, Any],
    stock: dict[tuple[str, str], float],
) -> float:
    """Counter + warehouse on-hand for one product, in reporting base units.

    Spirits → millilitres (bottle/can rows × pack size).
    Beer / Alcopop → bottle counts (mL rows kept as whole units when that is
    the product default, matching bottle-sold register rules).
    """
    name_key = _normalize_item_name(product.get("name") or "")
    bottle_page = _is_bottle_page_product(product)
    default_u = _stock_unit_key(product.get("default_unit") or "")
    variants = product.get("variants") or []
    bottle_ml = resolve_bottle_ml(variants)
    total = 0.0
    for (n, unit_key), qty in stock.items():
        if n != name_key:
            continue
        try:
            amount = float(qty or 0)
        except (TypeError, ValueError):
            continue
        if amount != amount:
            continue
        if bottle_page:
            if unit_key in ("bottle", "can", "pack", "pcs", "case") or unit_key == default_u:
                total += amount
            continue
        # Spirits: everything → mL
        if unit_key == "ml":
            total += amount
        elif unit_key == "liter":
            total += amount * 1000.0
        elif unit_key in ("bottle", "can", "pack", "pcs", "case"):
            total += amount * bottle_ml
        elif unit_key == default_u:
            total += amount
    return total


def _qty_to_opening_split(
    *,
    total_qty: float,
    unit: str,
    variants: list[dict[str, Any]],
) -> tuple[int, int, float, float]:
    """Return bottles, pegs, bottle_ml, total_base_qty (ml or count)."""
    unit_n = _stock_unit_key(unit)
    try:
        qty = float(total_qty)
    except (TypeError, ValueError):
        qty = 0.0
    if qty != qty:
        qty = 0.0

    if unit_n in ("bottle", "can", "pack", "pcs", "case"):
        bottles = int(math.floor(max(qty, 0.0)))
        return bottles, 0, 0.0, qty

    if unit_n in ("ml", "liter"):
        total_ml = qty * 1000.0 if unit_n == "liter" else qty
        bottle_ml = resolve_bottle_ml(variants)
        bottles, pegs = ml_to_bottles_and_pegs(total_ml, bottle_ml=bottle_ml)
        return bottles, pegs, bottle_ml, total_ml

    # Fallback: treat as whole units
    bottles = int(math.floor(max(qty, 0.0)))
    return bottles, 0, 0.0, qty


def _qty_received_to_bottles(
    qty: float,
    unit: str,
    variants: list[dict[str, Any]] | None,
) -> float:
    """Purchases are reported in bottles; convert mL receives using pack size."""
    try:
        amount = float(qty)
    except (TypeError, ValueError):
        return 0.0
    if amount <= 0 or amount != amount:
        return 0.0
    unit_n = _stock_unit_key(unit)
    if unit_n in ("bottle", "can", "pack", "pcs", "case"):
        return amount
    if unit_n == "liter":
        # Rare; treat liters as bottle-count when category is bottle-sold, else mL via pack.
        bottle_ml = resolve_bottle_ml(variants)
        return (amount * 1000.0) / bottle_ml if bottle_ml else amount
    if unit_n == "ml":
        bottle_ml = resolve_bottle_ml(variants)
        return amount / bottle_ml if bottle_ml else 0.0
    return amount


def _sum_bar_purchased_bottles(
    conn,
    products: list[dict[str, Any]],
    *,
    year: int,
    month: int,
) -> dict[str, int]:
    """Sum bar receive/inward qty in the report month, as whole bottles per product name."""
    last_day = calendar.monthrange(year, month)[1]
    date_from = f"{year:04d}-{month:02d}-01"
    date_to = f"{year:04d}-{month:02d}-{last_day:02d}"
    rows = conn.execute(
        """
        SELECT item_name, unit, COALESCE(SUM(qty_delta), 0) AS qty
        FROM store_stock_movements
        WHERE lower(trim(coalesce(outlet, ''))) = 'bar'
          AND lower(trim(coalesce(movement_type, ''))) = 'receive'
          AND lower(trim(coalesce(ref_type, ''))) IN (
              'stock_inward', 'stock_inward_direct', 'purchase_request'
          )
          AND qty_delta > 0
          AND date(created_at) >= ?
          AND date(created_at) <= ?
        GROUP BY item_name, unit
        """,
        (date_from, date_to),
    ).fetchall()

    by_name_variants = {
        _normalize_item_name(p["name"]): p.get("variants") or [] for p in products
    }
    totals: dict[str, float] = {}
    for row in rows:
        name_key = _normalize_item_name(row["item_name"])
        variants = by_name_variants.get(name_key) or []
        bottles = _qty_received_to_bottles(
            float(row["qty"] or 0),
            row["unit"] or "",
            variants,
        )
        totals[name_key] = totals.get(name_key, 0.0) + bottles

    return {
        key: int(math.floor(qty + 1e-9))
        for key, qty in totals.items()
        if qty > 0
    }


def _excl_bar_sale_rate(inclusive: float, *, tax: dict[str, Any], liquor: bool) -> float:
    """POS menu rates are tax-inclusive; DC Office wants sale rate without tax."""
    try:
        inc = float(inclusive or 0)
    except (TypeError, ValueError):
        return 0.0
    if inc <= 0 or inc != inc:
        return 0.0
    if not tax.get("prices_include_tax", True):
        return float(_pos_money(inc))
    if liquor:
        factor = 1.0 + float(tax.get("vat") or 0)
    else:
        factor = 1.0 + float(tax.get("cgst") or 0) + float(tax.get("ugst") or 0)
    if factor <= 1:
        return float(_pos_money(inc))
    return float(_pos_money(inc / factor))


def _classify_menu_sell_unit(qty: Any, unit: str) -> str | None:
    """Infer peg vs bottle from recipe qty/unit for **sold qty**.

    Any positive mL/liter pour counts as pegs (scaled to 30 ml). Bottle/can
    packs count as bottles. This covers 30 ml pegs and 60 ml doubles.
    """
    unit_n = _stock_unit_key(unit)
    try:
        amount = float(qty or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0 or amount != amount:
        return None
    if unit_n in ("ml", "liter"):
        return "peg"
    if unit_n in ("bottle", "can", "pcs", "pack", "case"):
        return "bottle"
    return None


def _classify_menu_rate_unit(qty: Any, unit: str) -> str | None:
    """Infer peg vs bottle menu for **sale rates** (strict portion sizes).

    Peg rate comes from ~30 ml serves only so cocktail 60 ml rows do not
    overwrite the peg price. Bottle rate from 1 bottle/can serve.
    """
    unit_n = _stock_unit_key(unit)
    try:
        amount = float(qty or 0)
    except (TypeError, ValueError):
        amount = 0.0
    if amount <= 0 or amount != amount:
        return None
    if unit_n == "ml" and 25 <= amount <= 35:
        return "peg"
    if unit_n in ("bottle", "can", "pcs", "pack", "case") and abs(amount - 1.0) < 1e-6:
        return "bottle"
    return None


def _sold_volume_from_insight_row(row: dict[str, Any]) -> tuple[float, float]:
    """Map one Unit Insight row to (sold_ml, sold_raw_bottles).

    mL/liter recipes accumulate as millilitres. Bottle/can serves accumulate as
    raw bottle counts (converted with the product pack size later).
    """
    try:
        line_qty = float(row.get("line_qty") or 0)
    except (TypeError, ValueError):
        return 0.0, 0.0
    if line_qty <= 0 or line_qty != line_qty:
        return 0.0, 0.0
    try:
        recipe_qty = float(row.get("recipe_qty") or 0)
    except (TypeError, ValueError):
        recipe_qty = 0.0
    recipe_unit = row.get("recipe_unit") or ""
    sell = _classify_menu_sell_unit(recipe_qty, recipe_unit)
    unit_n = _stock_unit_key(recipe_unit)

    if sell == "bottle" or unit_n in ("bottle", "can", "pcs", "pack", "case"):
        return 0.0, line_qty * (recipe_qty if recipe_qty > 0 else 1.0)
    if unit_n == "liter":
        ml = recipe_qty * 1000.0 if recipe_qty > 0 else 0.0
        return line_qty * ml, 0.0
    if unit_n == "ml" or sell == "peg":
        ml = recipe_qty if recipe_qty > 0 else DEFAULT_PEG_ML
        return line_qty * ml, 0.0
    return 0.0, 0.0


def _sum_bar_sold_volume(
    conn, *, year: int, month: int
) -> dict[str, dict[str, float]]:
    """POS sales in the report month → sold_ml + raw bottles per product name.

    Uses Unit Insight invoice×recipe rows across all POS outlets. Spirits H/I
    later split total mL the same way as Opening Stock (750 ml pack → 25 pegs
    per bottle: 25 pegs → 1 bottle 0 pegs; 26 pegs → 1 bottle 1 peg).
    """
    last_day = calendar.monthrange(year, month)[1]
    date_from = f"{year:04d}-{month:02d}-01"
    date_to = f"{year:04d}-{month:02d}-{last_day:02d}"
    raw = list_pos_unit_insights_raw(
        conn,
        date_from=date_from,
        date_to=date_to,
        outlet=None,
        settlement=None,
    )
    totals: dict[str, dict[str, float]] = {}
    for row in raw:
        name_key = _normalize_item_name(row.get("product_name") or "")
        if not name_key:
            continue
        sold_ml, sold_bottles = _sold_volume_from_insight_row(row)
        if sold_ml <= 0 and sold_bottles <= 0:
            continue
        bucket = totals.setdefault(name_key, {"ml": 0.0, "bottles_raw": 0.0})
        bucket["ml"] += sold_ml
        bucket["bottles_raw"] += sold_bottles
    return totals


def _spirits_sold_bottles_and_pegs(
    *,
    sold_ml: float,
    sold_bottles_raw: float,
    variants: list[dict[str, Any]] | None,
) -> tuple[int, int]:
    """Split spirits sales like Opening Stock: total mL → bottles + leftover pegs."""
    bottle_ml = resolve_bottle_ml(variants)
    try:
        raw_btl = float(sold_bottles_raw or 0)
    except (TypeError, ValueError):
        raw_btl = 0.0
    try:
        ml = float(sold_ml or 0)
    except (TypeError, ValueError):
        ml = 0.0
    if raw_btl != raw_btl:
        raw_btl = 0.0
    if ml != ml:
        ml = 0.0
    total_ml = max(ml, 0.0) + max(raw_btl, 0.0) * bottle_ml
    return ml_to_bottles_and_pegs(total_ml, bottle_ml=bottle_ml, peg_ml=DEFAULT_PEG_ML)


def _load_bar_sale_rates_excl(conn) -> dict[str, dict[str, float]]:
    """Map normalized bar product/menu name → peg/bottle rates without tax."""
    tax = get_pos_tax_rates(conn, "bar")
    rows = conn.execute(
        """
        SELECT m.id AS menu_id,
               m.name AS menu_name,
               m.rate AS rate_incl,
               lower(trim(coalesce(m.item_kind, ''))) AS item_kind,
               m.product_id AS product_id,
               p.name AS product_name,
               r.qty AS recipe_qty,
               r.unit AS recipe_unit
        FROM pos_menu_items m
        LEFT JOIN pos_menu_recipe_lines r ON r.menu_item_id = m.id
        LEFT JOIN store_products p ON p.id = m.product_id
        WHERE m.is_active = 1
          AND lower(trim(coalesce(m.outlet, ''))) = 'bar'
        """
    ).fetchall()

    # name_key → {"peg_incl": ..., "bottle_incl": ..., "liquor": bool}
    raw: dict[str, dict[str, Any]] = {}
    for row in rows:
        product_name = (row["product_name"] or "").strip()
        menu_name = (row["menu_name"] or "").strip()
        name_key = _normalize_item_name(product_name or menu_name)
        if not name_key:
            continue
        sell = _classify_menu_rate_unit(row["recipe_qty"], row["recipe_unit"] or "")
        if sell is None:
            continue
        try:
            rate_incl = float(row["rate_incl"] or 0)
        except (TypeError, ValueError):
            rate_incl = 0.0
        if rate_incl <= 0:
            continue
        liquor = (row["item_kind"] or "") == "liquor"
        bucket = raw.setdefault(
            name_key, {"peg_incl": 0.0, "bottle_incl": 0.0, "liquor": liquor}
        )
        bucket["liquor"] = bucket["liquor"] or liquor
        # Prefer first positive rate; keep higher if duplicates.
        key = "peg_incl" if sell == "peg" else "bottle_incl"
        prev = float(bucket.get(key) or 0)
        if rate_incl > prev:
            bucket[key] = rate_incl

    out: dict[str, dict[str, float]] = {}
    for name_key, bucket in raw.items():
        liquor = bool(bucket.get("liquor"))
        peg_excl = _excl_bar_sale_rate(
            float(bucket.get("peg_incl") or 0), tax=tax, liquor=liquor
        )
        bottle_excl = _excl_bar_sale_rate(
            float(bucket.get("bottle_incl") or 0), tax=tax, liquor=liquor
        )
        out[name_key] = {
            "peg_excl": peg_excl,
            "bottle_excl": bottle_excl,
        }
    return out


def _sale_rates_for_product(
    product: dict[str, Any],
    rates: dict[str, dict[str, float]],
) -> tuple[float | None, float | None]:
    """Return (bottle_excl, peg_excl); derive bottle from peg × pegs-per-bottle when needed."""
    name_key = _normalize_item_name(product.get("name") or "")
    info = rates.get(name_key) or {}
    peg = float(info.get("peg_excl") or 0)
    bottle = float(info.get("bottle_excl") or 0)
    if bottle <= 0 and peg > 0:
        bottle_ml = resolve_bottle_ml(product.get("variants") or [])
        pegs_per_bottle = bottle_ml / DEFAULT_PEG_ML if bottle_ml > 0 else 25.0
        bottle = float(_pos_money(peg * pegs_per_bottle))
    peg_out = peg if peg > 0 else None
    bottle_out = bottle if bottle > 0 else None
    return bottle_out, peg_out


def build_dc_office_opening_rows(
    conn, *, year: int | None = None, month: int | None = None
) -> list[dict[str, Any]]:
    """All active bar/both products with Opening Stock bottles + pegs.

    Opening stock = Bar **Counter + Warehouse** on-hand (combined).
    mL products → page ``spirits`` (convert to bottles + pegs 30ML).
    Beer / Alcopop → page ``beer`` (whole bottles only, pegs 0).
    Purchased (column E) = bar receive movements in the selected month, in bottles.
    Spirits sale rates (J bottle / L peg) are POS menu rates without tax.
    Spirits sold qty (H/I) = Unit Insight sales split like Opening Stock
    (total mL → bottles + leftover 30 ml pegs; 750 ml pack ⇒ 25 pegs/bottle).
    Beer sold qty (H) = whole bottles sold.
    """
    ensure_stores_schema(conn)
    products = _load_bar_products(conn)
    stock = _sum_bar_counter_warehouse_qty(conn)
    sale_rates = _load_bar_sale_rates_excl(conn)
    today = date.today()
    purchase_year = int(year or today.year)
    purchase_month = int(month or today.month)
    purchased = _sum_bar_purchased_bottles(
        conn, products, year=purchase_year, month=purchase_month
    )
    sold_volume = _sum_bar_sold_volume(
        conn, year=purchase_year, month=purchase_month
    )

    spirits: list[dict[str, Any]] = []
    beer: list[dict[str, Any]] = []
    for product in products:
        name = product["name"]
        unit = product["default_unit"]
        total_qty = _combined_on_hand_for_product(product, stock)
        bottle_page = _is_bottle_page_product(product)
        rate_bottle, rate_peg = _sale_rates_for_product(product, sale_rates)
        name_key = _normalize_item_name(name)
        vol = sold_volume.get(name_key) or {}
        sold_ml = float(vol.get("ml") or 0)
        sold_bottles_raw = float(vol.get("bottles_raw") or 0)
        if bottle_page:
            # Whole bottles/cans only — never convert into mL / pegs.
            bottles = int(math.floor(max(total_qty, 0.0)))
            pegs = 0
            bottle_ml = 0.0
            total_base = float(total_qty)
            page = "beer"
            target = beer
            row_sold_bottles = int(math.floor(max(sold_bottles_raw, 0.0) + 1e-9))
            row_sold_pegs = 0
        else:
            bottles, pegs, bottle_ml, total_base = _qty_to_opening_split(
                total_qty=total_qty,
                unit="mL",
                variants=product["variants"],
            )
            page = "spirits"
            target = spirits
            row_sold_bottles, row_sold_pegs = _spirits_sold_bottles_and_pegs(
                sold_ml=sold_ml,
                sold_bottles_raw=sold_bottles_raw,
                variants=product["variants"],
            )
        target.append(
            {
                "name": name,
                "bottles": bottles,
                "pegs_30ml": pegs,
                "opening_qty": float(bottles),
                "purchased_bottles": int(purchased.get(name_key, 0) or 0),
                "sold_bottles": row_sold_bottles,
                "sold_pegs": row_sold_pegs,
                "rate_per_bottle": rate_bottle,
                "rate_per_peg": rate_peg,
                "product_id": product["id"],
                "unit": unit,
                "category_name": product.get("category_name") or "",
                "total_base_qty": round(total_base, 4),
                "bottle_ml": bottle_ml,
                "page": page,
            }
        )

    rows: list[dict[str, Any]] = []
    sno = 1
    for page_rows in (spirits, beer):
        page_sno = 1
        for row in page_rows:
            row["sno"] = page_sno
            row["global_sno"] = sno
            rows.append(row)
            page_sno += 1
            sno += 1
    return rows


def _month_year_from_args(args, *, today: date | None = None) -> tuple[int, int]:
    today = today or date.today()
    try:
        year = int(args.get("year") or today.year)
    except (TypeError, ValueError):
        year = today.year
    try:
        month = int(args.get("month") or today.month)
    except (TypeError, ValueError):
        month = today.month
    if month < 1 or month > 12:
        month = today.month
    if year < 2000 or year > 2100:
        year = today.year
    return year, month


def month_label(year: int, month: int) -> str:
    return f"{calendar.month_name[month].upper()} {year}"


def _update_title_header(ws, *, month_label_text: str) -> None:
    cell = ws.cell(HEADER_TITLE_ROW, 1)
    raw = cell.value
    title = f"Bar Monthly Sale and Stock Register of {month_label_text}"
    if raw is None or not str(raw).strip():
        cell.value = title
        return
    text = str(raw)
    if _MONTH_TOKEN_RE.search(text):
        cell.value = _MONTH_TOKEN_RE.sub(month_label_text, text, count=1)
        return
    for mname in calendar.month_name[1:]:
        if re.search(rf"\b{re.escape(mname)}\b", text, flags=re.IGNORECASE):
            cell.value = re.sub(
                rf"\b{re.escape(mname)}\b(\s+\d{{4}})?",
                month_label_text,
                text,
                count=1,
                flags=re.IGNORECASE,
            )
            return
    cell.value = title


def _unmerge_rows(ws, *, start_row: int, end_row: int) -> None:
    """Unmerge any ranges that overlap the given row span."""
    to_remove: list[str] = []
    for merged in list(ws.merged_cells.ranges):
        if merged.max_row < start_row or merged.min_row > end_row:
            continue
        to_remove.append(str(merged))
    for ref in to_remove:
        ws.unmerge_cells(ref)


def _empty_border():
    from openpyxl.styles import Border

    return Border()


def _thin_border():
    from openpyxl.styles import Border, Side

    thin = Side(style="thin")
    return Border(left=thin, right=thin, top=thin, bottom=thin)


def _apply_data_row_borders(ws, row: int) -> None:
    """Match Spirits register row borders (medium outer edges on A / D / Q)."""
    from openpyxl.styles import Border, Side

    thin = Side(style="thin")
    medium = Side(style="medium")
    for c in range(1, 18):
        left = medium if c == 1 else thin
        right = medium if c in (4, 17) else thin
        ws.cell(row, c).border = Border(
            left=left, right=right, top=thin, bottom=thin
        )


def _apply_beer_data_row_borders(ws, row: int) -> None:
    """Beer sheet borders after dropping empty J/K — register ends at column O."""
    from openpyxl.styles import Border, Side

    thin = Side(style="thin")
    medium = Side(style="medium")
    for c in range(1, 16):
        left = medium if c == 1 else thin
        right = medium if c in (4, 15) else thin
        ws.cell(row, c).border = Border(
            left=left, right=right, top=thin, bottom=thin
        )


def _beer_compact_header_row(values: list[Any]) -> list[Any]:
    """Drop empty template cols J/K; shift L–Q left into J–O."""
    # values[0]=A … values[16]=Q (17 cells). Keep A–I, skip J–K, keep L–Q.
    padded = list(values) + [None] * max(0, 17 - len(values))
    return list(padded[:9]) + list(padded[11:17])


def _copy_row_style(source_ws, source_row: int, target_ws, target_row: int, *, max_col: int = 17) -> None:
    from copy import copy

    for c in range(1, max_col + 1):
        src = source_ws.cell(source_row, c)
        dst = target_ws.cell(target_row, c)
        if src.has_style:
            dst.font = copy(src.font)
            dst.border = copy(src.border)
            dst.fill = copy(src.fill)
            dst.number_format = src.number_format
            dst.alignment = copy(src.alignment)


def _empty_fill():
    from openpyxl.styles import PatternFill

    return PatternFill(fill_type=None)


def _clear_cell(ws, row: int, col: int) -> None:
    """Clear value, border, and fill so empty fields have no leftover template styling."""
    from openpyxl.cell.cell import MergedCell

    cell = ws.cell(row, col)
    if isinstance(cell, MergedCell):
        return
    cell.value = None
    cell.border = _empty_border()
    cell.fill = _empty_fill()


def _set_cell_value(ws, row: int, col: int, value, *, blank_keeps_border: bool = False) -> None:
    from openpyxl.cell.cell import MergedCell

    cell = ws.cell(row, col)
    if isinstance(cell, MergedCell):
        return
    cell.value = value
    if value is None or value == "":
        cell.fill = _empty_fill()
        if blank_keeps_border:
            cell.border = _thin_border()
        else:
            cell.border = _empty_border()


def _write_spirits_data_row(ws, row: int, item: dict[str, Any] | None) -> None:
    """Write one spirits-page row; J/L are sale rates without tax."""
    r = row
    if item is None:
        for c in range(1, 28):
            _clear_cell(ws, r, c)
        return
    _set_cell_value(ws, r, 1, int(item["sno"]))
    _set_cell_value(ws, r, 2, item["name"])
    _set_cell_value(ws, r, 3, int(item["bottles"]))
    _set_cell_value(ws, r, 4, int(item["pegs_30ml"]))
    purchased = int(item.get("purchased_bottles") or 0)
    _set_cell_value(ws, r, 5, purchased)  # Purchased Bottel (all purchases in bottles)
    _set_cell_value(ws, r, 6, f"=C{r}+E{r}")  # Total Stock Bottel
    _set_cell_value(ws, r, 7, f"=D{r}")  # Total Stock Pegs
    _set_cell_value(ws, r, 8, int(item.get("sold_bottles") or 0))  # Sale Bottel
    _set_cell_value(ws, r, 9, int(item.get("sold_pegs") or 0))  # Sale Pegs
    rate_bottle = item.get("rate_per_bottle")
    rate_peg = item.get("rate_per_peg")
    # J = sale rate per bottle (excl tax); K keeps total-peg math without using J.
    if rate_bottle is None:
        _set_cell_value(ws, r, 10, None, blank_keeps_border=True)
    else:
        _set_cell_value(ws, r, 10, float(rate_bottle))
    _set_cell_value(ws, r, 11, f"=I{r}+H{r}*25")  # total peg
    # L = sale rate per peg (excl tax)
    if rate_peg is None:
        _set_cell_value(ws, r, 12, None, blank_keeps_border=True)
    else:
        _set_cell_value(ws, r, 12, float(rate_peg))
    _set_cell_value(ws, r, 13, f"=H{r}*J{r}+I{r}*L{r}")  # Total Amt
    _set_cell_value(ws, r, 14, 0)  # Discard Bottel
    _set_cell_value(ws, r, 15, 0)  # Discard Pegs
    # Closing = Total Stock − Sales (F/G − H/I); discard N/O still subtracted when used.
    _set_cell_value(ws, r, 16, f"=F{r}-H{r}-N{r}")  # Closing Bottel
    _set_cell_value(ws, r, 17, f"=G{r}-I{r}-O{r}")  # Closing Pegs
    # Clear leftover template columns beyond the register block.
    for c in range(18, 28):
        _clear_cell(ws, r, c)


def _write_beer_data_row(ws, row: int, item: dict[str, Any] | None) -> None:
    """Write one beer-page row; empty J/K from spirits layout are omitted (cols shift left)."""
    r = row
    if item is None:
        for c in range(1, 28):
            _clear_cell(ws, r, c)
        return
    _set_cell_value(ws, r, 1, int(item["sno"]))
    _set_cell_value(ws, r, 2, item["name"])
    _set_cell_value(ws, r, 3, int(item["bottles"]))
    _set_cell_value(ws, r, 4, 0)  # Pegs unused for bottle-sold
    purchased = int(item.get("purchased_bottles") or 0)
    _set_cell_value(ws, r, 5, purchased)  # Purchased Bottel
    _set_cell_value(ws, r, 6, f"=C{r}+E{r}")
    _set_cell_value(ws, r, 7, 0)
    _set_cell_value(ws, r, 8, int(item.get("sold_bottles") or 0))  # Sale Bottel/Can
    _set_cell_value(ws, r, 9, 0)
    # No spirits-style empty J/K — rate/amount/discard/closing start at J.
    rate_bottle = item.get("rate_per_bottle")
    if rate_bottle is None:
        _set_cell_value(ws, r, 10, None, blank_keeps_border=True)  # rate per btl
    else:
        _set_cell_value(ws, r, 10, float(rate_bottle))
    _set_cell_value(ws, r, 11, f"=H{r}*J{r}")  # total amt
    _set_cell_value(ws, r, 12, 0)  # Discard Bottel
    _set_cell_value(ws, r, 13, 0)  # Discard Pegs
    _set_cell_value(ws, r, 14, f"=F{r}-H{r}-L{r}")  # Closing Bottel
    _set_cell_value(ws, r, 15, 0)  # Closing Pegs
    for c in range(16, 28):
        _clear_cell(ws, r, c)
    _apply_beer_data_row_borders(ws, r)


def _copy_cell_style_and_value(source, target) -> None:
    from copy import copy
    from openpyxl.cell.cell import MergedCell

    if isinstance(target, MergedCell) or isinstance(source, MergedCell):
        return
    target.value = source.value
    if source.has_style:
        target.font = copy(source.font)
        target.border = copy(source.border)
        target.fill = copy(source.fill)
        target.number_format = source.number_format
        target.alignment = copy(source.alignment)
    if target.value is None or target.value == "":
        target.border = _empty_border()


def _clear_sheet_rows(ws, *, start_row: int, end_row: int, max_col: int = 28) -> None:
    _unmerge_rows(ws, start_row=start_row, end_row=end_row)
    for r in range(start_row, end_row + 1):
        for c in range(1, max_col + 1):
            _clear_cell(ws, r, c)


def build_dc_office_workbook(
    rows: list[dict[str, Any]],
    *,
    month_label_text: str,
    template_path: str | Path | None = None,
):
    """July DC Office format: Sheet1 Spirits, Sheet2 Beer/Alcopop (not one sheet)."""
    path = Path(template_path) if template_path else _TEMPLATE_PATH
    wb = load_workbook(path)
    ws1 = wb.active
    ws1.title = "Spirits"

    _update_title_header(ws1, month_label_text=month_label_text)

    # Drop unused far header labels from the July template.
    for col in (23, 25):  # W6, Y6
        _clear_cell(ws1, 6, col)
    # Spirits: J is sale rate per bottle (excl tax); L remains rate per peg.
    _set_cell_value(ws1, 6, 10, "Rate per bottle")
    _set_cell_value(ws1, 6, 12, "Rate per peg")

    spirits = [r for r in rows if r.get("page") == "spirits"]
    beer = [r for r in rows if r.get("page") == "beer"]

    spirits_slots = SPIRITS_DATA_END - SPIRITS_DATA_START + 1
    for offset in range(spirits_slots):
        item = spirits[offset] if offset < len(spirits) else None
        _write_spirits_data_row(ws1, SPIRITS_DATA_START + offset, item)

    # Snapshot beer section headers (template rows 66–68) before clearing sheet 1.
    beer_header_snapshot: list[list[Any]] = []
    for r in (66, 67, 68):
        beer_header_snapshot.append(
            [ws1.cell(r, c).value for c in range(1, 18)]
        )

    # Sheet 1 must not include Beer/Alcopop — clear lower section.
    _clear_sheet_rows(ws1, start_row=64, end_row=max(int(ws1.max_row or 64), 97))

    # Sheet 2: Beer & Alcopop with same hotel header + beer column layout.
    if "Beer Alcopop" in wb.sheetnames:
        del wb["Beer Alcopop"]
    ws2 = wb.create_sheet("Beer Alcopop")

    for key, dim in ws1.column_dimensions.items():
        if dim.width is not None:
            ws2.column_dimensions[key].width = dim.width

    # Copy hotel / title rows 1–4 (values + style) and their merges.
    for r in range(1, 5):
        for c in range(1, 18):
            _copy_cell_style_and_value(ws1.cell(r, c), ws2.cell(r, c))
    for merged in list(ws1.merged_cells.ranges):
        if merged.max_row <= 4:
            try:
                ws2.merge_cells(str(merged))
            except ValueError:
                pass

    # Beer headers → sheet2 rows 5–7 (from template 66–68), without empty J/K.
    compacted_headers = [_beer_compact_header_row(vals) for vals in beer_header_snapshot]
    for idx, values in enumerate(compacted_headers):
        r = 5 + idx
        for c, val in enumerate(values, start=1):
            _set_cell_value(ws2, r, c, val)
        for c in range(len(values) + 1, 18):
            _clear_cell(ws2, r, c)
    # Match Spirits header border/font styling on rows 5–6 (A–O only).
    _copy_row_style(ws1, 5, ws2, 5, max_col=15)
    _copy_row_style(ws1, 6, ws2, 6, max_col=15)
    # Re-apply beer-specific header labels after style copy (already compacted).
    for c, val in enumerate(compacted_headers[0], start=1):
        if val is not None:
            ws2.cell(5, c).value = val
    for c, val in enumerate(compacted_headers[1], start=1):
        if val is not None:
            ws2.cell(6, c).value = val
    for c in range(16, 18):
        _clear_cell(ws2, 5, c)
        _clear_cell(ws2, 6, c)
    _set_cell_value(ws2, 7, 1, "BEER / ALCOPOP")
    ws2.cell(7, 1).fill = _empty_fill()
    # Section label row — same outer border language as Spirits data rows.
    from openpyxl.styles import Border, Side, Font

    thin = Side(style="thin")
    medium = Side(style="medium")
    ws2.cell(7, 1).border = Border(
        left=medium, right=thin, top=thin, bottom=thin
    )
    ws2.cell(7, 1).font = Font(bold=True)

    # Header merges after dropping empty J/K: Discard L:M, Closing N:O.
    for ref in ("C5:D5", "F5:G5", "H5:I5", "L5:M5", "N5:O5"):
        try:
            ws2.merge_cells(ref)
        except ValueError:
            pass

    beer_data_start = 8
    for offset, item in enumerate(beer):
        _write_beer_data_row(ws2, beer_data_start + offset, item)

    return wb


def build_dc_office_report(conn, *, year: int, month: int, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    rows = build_dc_office_opening_rows(conn, year=year, month=month)
    label = month_label(year, month)
    return {
        "rows": rows,
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "month_label": label,
        "today": today,
        "product_count": len(rows),
        "bottles_total": sum(int(r["bottles"]) for r in rows),
        "pegs_total": sum(int(r["pegs_30ml"]) for r in rows),
    }


def _hub_kwargs():
    from_hub = (request.args.get("from_hub") or "").strip()
    hub_kwargs = {}
    if from_hub:
        hub_kwargs["from_hub"] = from_hub
    return from_hub, hub_kwargs


def _load_page_payload():
    year, month = _month_year_from_args(request.args)
    conn = get_db()
    try:
        ensure_stores_schema(conn)
        return build_dc_office_report(conn, year=year, month=month)
    finally:
        conn.close()


def register_dc_office(app):
    """Register DC Office page and Excel export."""

    @app.route("/reports/sales/dc-office", endpoint="sales_report_dc_office")
    def sales_report_dc_office():
        payload = _load_page_payload()
        from_hub, hub_kwargs = _hub_kwargs()
        export_kwargs = dict(hub_kwargs)
        export_kwargs["month"] = payload["month"]
        export_kwargs["year"] = payload["year"]
        return render_template(
            "dc_office_report.html",
            de_nav_section="report",
            de_nav_report_view="home",
            page_title=DC_OFFICE_TITLE,
            rows=payload["rows"],
            product_count=payload["product_count"],
            bottles_total=payload["bottles_total"],
            pegs_total=payload["pegs_total"],
            sel_year=payload["year"],
            sel_month=payload["month"],
            month_name=payload["month_name"],
            month_label=payload["month_label"],
            today_year=payload["today"].year,
            filter_form_action=url_for("sales_report_dc_office", **hub_kwargs),
            dc_office_export_url=url_for("sales_report_dc_office_export", **export_kwargs),
            dc_office_export_filename=report_export_month_filename(
                DC_OFFICE_EXPORT_TITLE, payload["year"], payload["month"]
            ),
            preserve_from_hub=bool(from_hub),
            from_hub=from_hub,
            back_href=url_for("reports") if from_hub else None,
            back_label="Back to Reports" if from_hub else None,
        )

    @app.route(
        "/reports/sales/dc-office/export",
        endpoint="sales_report_dc_office_export",
    )
    def sales_report_dc_office_export():
        payload = _load_page_payload()
        wb = build_dc_office_workbook(
            payload["rows"], month_label_text=payload["month_label"]
        )
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        fname = report_export_month_filename(
            DC_OFFICE_EXPORT_TITLE, payload["year"], payload["month"]
        )
        response = send_file(
            buf,
            as_attachment=True,
            download_name=fname,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        return response
