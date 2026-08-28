"""Plain dataclasses — never import Flask or db."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class UserSession:
    authenticated: bool = False
    username: str = ""
    display_name: str = ""
    must_change_password: bool = False
    captcha_required: bool = False
    error: str = ""
    access: dict[str, Any] = field(default_factory=dict)


@dataclass
class Product:
    id: int
    name: str
    default_unit: str = ""
    outlet: str = ""
    approximate_price: Optional[float] = None
    category_name: str = ""

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> "Product":
        price = row.get("approximate_price")
        try:
            price_f = float(price) if price is not None and price != "" else None
        except (TypeError, ValueError):
            price_f = None
        return cls(
            id=int(row.get("id") or 0),
            name=str(row.get("name") or ""),
            default_unit=str(row.get("default_unit") or ""),
            outlet=str(row.get("outlet") or ""),
            approximate_price=price_f,
            category_name=str(row.get("category_name") or ""),
        )


@dataclass
class MenuItem:
    id: int
    name: str
    rate: float = 0.0
    category_id: Optional[int] = None
    category_name: str = ""
    variant: str = ""

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> "MenuItem":
        try:
            rate = float(row.get("rate") or row.get("price") or row.get("sale_price") or 0)
        except (TypeError, ValueError):
            rate = 0.0
        cat_id = row.get("category_id") or row.get("categoryId")
        try:
            cat_id_i = int(cat_id) if cat_id is not None else None
        except (TypeError, ValueError):
            cat_id_i = None
        return cls(
            id=int(row.get("id") or row.get("menuId") or 0),
            name=str(row.get("name") or ""),
            rate=rate,
            category_id=cat_id_i,
            category_name=str(row.get("category_name") or row.get("category") or ""),
            variant=str(row.get("variant") or ""),
        )


@dataclass
class InvoiceLine:
    uid: str
    name: str
    rate: float
    qty: float
    menu_id: Optional[int] = None
    variant: str = ""
    kot_sent_qty: float = 0.0

    def to_api(self) -> dict[str, Any]:
        return {
            "uid": self.uid,
            "menuId": self.menu_id,
            "name": self.name,
            "variant": self.variant,
            "rate": self.rate,
            "qty": self.qty,
            "kotSentQty": self.kot_sent_qty,
        }


@dataclass
class NotificationItem:
    id: str
    title: str
    body: str
    href: str = ""

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> "NotificationItem":
        return cls(
            id=str(row.get("id") or ""),
            title=str(row.get("title") or ""),
            body=str(row.get("body") or ""),
            href=str(row.get("href") or ""),
        )


@dataclass
class OutstandingExpense:
    id: int
    supplier_id: int
    supplier_name: str
    expense_code: str
    description: str
    amount: float
    balance: float
    sales_date: str = ""
    category: str = ""
    entry_kind: str = "expense"

    @classmethod
    def from_api(cls, row: dict[str, Any]) -> "OutstandingExpense":
        def _f(key: str, default: float = 0.0) -> float:
            try:
                return float(row.get(key) or default)
            except (TypeError, ValueError):
                return default

        def _i(key: str) -> int:
            try:
                return int(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        return cls(
            id=_i("id"),
            supplier_id=_i("supplier_id"),
            supplier_name=str(row.get("supplier_name") or ""),
            expense_code=str(row.get("expense_code") or ""),
            description=str(row.get("description") or ""),
            amount=_f("amount"),
            balance=_f("balance"),
            sales_date=str(row.get("sales_date") or ""),
            category=str(row.get("category") or ""),
            entry_kind=str(row.get("entry_kind") or "expense"),
        )


@dataclass
class VerificationEntry:
    id: int
    supplier_name: str
    total_amount: float
    payment_date: str = ""
    verification_account: str = ""
    allocation_count: int = 0
    expense_codes: str = ""

    @classmethod
    def from_history_row(cls, row: dict[str, Any]) -> "VerificationEntry":
        def _f(key: str) -> float:
            try:
                return float(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        def _i(key: str) -> int:
            try:
                return int(row.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        return cls(
            id=_i("id"),
            supplier_name=str(row.get("supplier_name") or ""),
            total_amount=_f("total_amount"),
            payment_date=str(row.get("payment_date") or row.get("verification_date") or ""),
            verification_account=str(row.get("verification_account") or ""),
            allocation_count=_i("allocation_count"),
            expense_codes=str(row.get("expense_codes") or ""),
        )


@dataclass
class DashboardSnapshot:
    """Parsed /main-dashboard #md-dashboard-data embed for the Kivy Dashboard."""

    period: str = ""
    location: str = ""
    kpis: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)
    sales_trend: dict[str, Any] = field(default_factory=dict)
    company_leaderboard: list[dict[str, Any]] = field(default_factory=list)
    payment_mix: dict[str, Any] = field(default_factory=dict)
    top_selling_items: list[dict[str, Any]] = field(default_factory=list)
    top_selling_items_by_revenue: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class IndentLine:
    item_name: str
    quantity: float
    unit: str = "pcs"
    approximate_price: float = 0.0
    pack_label: str = ""
    pack_qty_in_base: Optional[float] = None

    def to_api(self) -> dict[str, Any]:
        return {
            "item_name": self.item_name,
            "quantity": self.quantity,
            "unit": self.unit,
            "approximate_price": self.approximate_price,
            "pack_label": self.pack_label,
            "pack_qty_in_base": self.pack_qty_in_base,
        }

