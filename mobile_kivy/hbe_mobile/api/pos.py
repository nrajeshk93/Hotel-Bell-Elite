"""Point-of-sale JSON APIs (restaurant prefix by default)."""

from __future__ import annotations

from typing import Any, Optional

from hbe_mobile.api.client import ApiClient, ApiError
from hbe_mobile.models import InvoiceLine, MenuItem


class PosApi:
    def __init__(self, client: ApiClient, *, base: str = "/point-of-sale"):
        self.client = client
        self.base = base.rstrip("/")

    def _path(self, suffix: str) -> str:
        return f"{self.base}{suffix}"

    def floor(self) -> dict[str, Any]:
        data = self.client.get_json(self._path("/api/floor"))
        if isinstance(data, dict) and data.get("ok") is False:
            raise ApiError(str(data.get("error") or "Floor load failed"))
        return data if isinstance(data, dict) else {}

    def menu_items(self) -> list[MenuItem]:
        data = self.client.get_json(self._path("/api/menu/items"))
        rows = []
        if isinstance(data, dict):
            rows = data.get("items") or data.get("menu") or data.get("products") or []
            if not rows and data.get("ok") and isinstance(data.get("data"), list):
                rows = data["data"]
        elif isinstance(data, list):
            rows = data
        return [MenuItem.from_api(r) for r in rows if isinstance(r, dict)]

    def menu_categories(self) -> list[dict[str, Any]]:
        data = self.client.get_json(self._path("/api/menu/categories"))
        if isinstance(data, dict):
            cats = data.get("categories") or data.get("items") or []
            return [c for c in cats if isinstance(c, dict)]
        return []

    def invoice_by_table(self, table: str) -> Optional[dict[str, Any]]:
        data = self.client.get_json(self._path("/api/invoices/by-table"), params={"table": table})
        if not isinstance(data, dict):
            return None
        if data.get("ok") is False:
            return None
        return data.get("invoice")

    def save_invoice(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = self.client.post_json(self._path("/api/invoices"), payload)
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Save failed"), payload=data)
        return data

    def send_kot(self, invoice_id: int) -> dict[str, Any]:
        data = self.client.post_json(self._path(f"/api/invoices/{invoice_id}/send-kot"), {})
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "KOT failed"), payload=data)
        return data

    def list_kot_tokens(self) -> dict[str, Any]:
        """Active kitchen tokens (sent, not yet customer-billed)."""
        data = self.client.get_json(self._path("/api/kot-tokens"))
        if isinstance(data, dict) and data.get("ok") is False:
            raise ApiError(str(data.get("error") or "KOT tokens load failed"), payload=data)
        return data if isinstance(data, dict) else {}

    def reduce_kot_tokens(
        self,
        changes: list[dict[str, Any]],
        reason: str = "",
    ) -> dict[str, Any]:
        """Edit kitchen-sent quantities (requires KOT Cancellation)."""
        payload = build_kot_reduce_payload(changes, reason=reason)
        data = self.client.post_json(self._path("/api/kot-tokens/reduce"), payload)
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(
                str((data or {}).get("error") if isinstance(data, dict) else "KOT edit failed"),
                payload=data,
            )
        return data

    def settle(self, invoice_id: int, payload: Optional[dict] = None) -> dict[str, Any]:
        data = self.client.post_json(self._path(f"/api/invoices/{invoice_id}/settle"), payload or {})
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Settle failed"), payload=data)
        return data

    def close(self, invoice_id: int) -> dict[str, Any]:
        data = self.client.post_json(self._path(f"/api/invoices/{invoice_id}/close"), {})
        if not isinstance(data, dict) or not data.get("ok"):
            raise ApiError(str((data or {}).get("error") if isinstance(data, dict) else "Close failed"), payload=data)
        return data


def has_pending_kot(lines: list[InvoiceLine]) -> bool:
    """True when any line still has qty not yet confirmed to the kitchen."""
    return any(
        float(line.qty or 0) > float(line.kot_sent_qty or 0) + 1e-9
        for line in (lines or [])
    )


def build_kot_reduce_payload(
    changes: list[dict[str, Any]],
    *,
    reason: str = "",
) -> dict[str, Any]:
    """Body for POST /api/kot-tokens/reduce."""
    normalized: list[dict[str, Any]] = []
    for row in changes or []:
        if not isinstance(row, dict):
            continue
        try:
            invoice_id = int(row.get("invoice_id") or row.get("invoiceId") or 0)
            line_id = int(row.get("line_id") or row.get("lineId") or row.get("id") or 0)
            sent_qty = float(row.get("sent_qty") if row.get("sent_qty") is not None else row.get("qty") or 0)
        except (TypeError, ValueError):
            continue
        if invoice_id <= 0 or line_id <= 0:
            continue
        normalized.append(
            {
                "invoice_id": invoice_id,
                "line_id": line_id,
                "sent_qty": max(0.0, sent_qty),
            }
        )
    payload: dict[str, Any] = {"changes": normalized}
    note = (reason or "").strip()
    if note:
        payload["reason"] = note
    return payload


def format_kot_slip_text(
    token: dict[str, Any],
    lines: Optional[list[dict[str, Any]]] = None,
    *,
    resend: bool = True,
) -> str:
    """Plain-text KOT slip for on-device preview / share (mirrors web reprint)."""
    rows = lines if lines is not None else (token.get("lines") or [])
    order_no = (token.get("kot_no") or token.get("order_no") or "—")
    table = (token.get("name") or token.get("table") or "—")
    heading = "KITCHEN ORDER TOKEN"
    parts = [
        heading,
        "REPRINT / RESEND" if resend else "KITCHEN ORDER",
        f"Order  {order_no}",
        f"Table  {table}",
        "Type   Dine In",
        f"Items  {len(rows)}",
        "-" * 28,
    ]
    for line in rows:
        if not isinstance(line, dict):
            continue
        qty = line.get("sent_qty")
        if qty is None:
            qty = line.get("qty")
        try:
            qty_n = float(qty or 0)
        except (TypeError, ValueError):
            qty_n = 0.0
        name = str(line.get("name") or "Item")
        variant = str(line.get("variant") or "").strip()
        notes = str(line.get("notes") or "").strip()
        label = f"{name} ({variant})" if variant else name
        parts.append(f"{qty_n:g}  {label}")
        if notes:
            parts.append(f"    note: {notes}")
    parts.append("-" * 28)
    parts.append("-- Resent for kitchen --" if resend else "-- End of KOT --")
    return "\n".join(parts)


def calc_bill_totals(
    lines: list[InvoiceLine],
    *,
    discount_pct: float = 0.0,
    service_pct: float = 0.0,
    tip: float = 0.0,
    prices_include_tax: bool = True,
) -> dict[str, float]:
    """Inclusive-tax bill summary (CGST 2.5% + SGST/UGST 2.5%)."""
    gross = round(sum(line.rate * line.qty for line in lines), 2)
    discount = round(gross * max(0.0, float(discount_pct or 0)) / 100.0, 2)
    after_disc = max(0.0, round(gross - discount, 2))
    service = round(after_disc * max(0.0, float(service_pct or 0)) / 100.0, 2)
    tip_amt = round(max(0.0, float(tip or 0)), 2)
    inclusive = round(after_disc + service + tip_amt, 2)
    if prices_include_tax and inclusive > 0:
        taxable = inclusive / 1.05
        cgst = round(taxable * 0.025, 2)
        sgst = round(taxable * 0.025, 2)
    else:
        cgst = round(inclusive * 0.025, 2)
        sgst = round(inclusive * 0.025, 2)
        inclusive = round(inclusive + cgst + sgst, 2)
    rounded = round(inclusive)
    round_off = round(rounded - inclusive, 2)
    total = round(inclusive + round_off, 2)
    return {
        "subtotal": gross,
        "discount": discount,
        "service": service,
        "tip": tip_amt,
        "cgst": cgst,
        "sgst": sgst,
        "gst": round(cgst + sgst, 2),
        "roundOff": round_off,
        "total": total,
    }


def build_invoice_payload(
    *,
    order_no: str,
    table: str,
    lines: list[InvoiceLine],
    order_type: str = "dine_in",
    customer_name: str = "Guest",
    customer_mobile: str = "",
    notes: str = "",
    kot_send: bool = False,
    customer_bill: bool = False,
    invoice_id: Optional[int] = None,
    discount_pct: float = 0.0,
    service_pct: float = 0.0,
    tip: float = 0.0,
    coupon_code: str = "",
) -> dict[str, Any]:
    totals = calc_bill_totals(
        lines,
        discount_pct=discount_pct,
        service_pct=service_pct,
        tip=tip,
        prices_include_tax=True,
    )
    payload: dict[str, Any] = {
        "orderNo": order_no,
        "table": table,
        "orderType": order_type,
        "order_type": order_type,
        "customerName": customer_name,
        "customerMobile": customer_mobile,
        "notes": notes,
        "kotSend": kot_send,
        "customerBill": customer_bill,
        "discountType": "pct",
        "discountValue": discount_pct,
        "serviceType": "pct",
        "serviceValue": service_pct,
        "tipAmount": tip,
        "couponCode": coupon_code,
        "taxCgstPct": 2.5,
        "taxUgstPct": 2.5,
        "lines": [],
        "totals": {
            "subtotal": totals["subtotal"],
            "discount": totals["discount"],
            "discountType": "pct",
            "discountValue": discount_pct,
            "gst": totals["gst"],
            "cgst": totals["cgst"],
            "ugst": totals["sgst"],
            "service": totals["service"],
            "serviceType": "pct",
            "serviceValue": service_pct,
            "tip": totals["tip"],
            "roundOff": totals["roundOff"],
            "total": totals["total"],
        },
    }
    for line in lines:
        row = line.to_api()
        if kot_send:
            qty = float(line.qty or 0)
            sent = float(line.kot_sent_qty or 0)
            if qty > sent + 1e-9:
                row["kotSentQty"] = qty
        payload["lines"].append(row)
    if invoice_id:
        payload["id"] = invoice_id
    return payload
