"""POS Invoice — mobile layout matching the restaurant billing mock."""

from __future__ import annotations

import time
import uuid

from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField
from kivymd.toast import toast

from hbe_mobile import theme
from hbe_mobile.api.pos import PosApi, build_invoice_payload, calc_bill_totals, has_pending_kot
from hbe_mobile.models import InvoiceLine, MenuItem
from hbe_mobile.utils.async_jobs import run_async


def _inr(value: float) -> str:
    return f"₹{value:,.2f}"


class PosInvoiceScreen(MDScreen):
    def __init__(self, app, *, outlet: str = "restaurant", api_base: str = "/point-of-sale", **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "pos_invoice"
        self.outlet = (outlet or "restaurant").strip().lower() or "restaurant"
        if self.outlet not in {"restaurant", "bar"}:
            self.outlet = "restaurant"
        self.md_bg_color = theme.BG
        self.pos_api = PosApi(app.api, base=api_base)
        self._menu: list[MenuItem] = []
        self._lines: list[InvoiceLine] = []
        self._invoice_id = None
        self._invoice_generated = False
        self._tables: list[str] = []
        self._discount_pct = 0.0
        self._service_pct = 0.0
        self._tip = 0.0

        root = MDBoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))

        selectors = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8))
        self.table_field = MDTextField(
            hint_text="Table",
            text="",
            size_hint_x=0.55,
            helper_text="e.g. Table 1",
            helper_text_mode="on_focus",
        )
        self.order_type_field = MDTextField(
            hint_text="Order type",
            text="dine_in",
            size_hint_x=0.45,
        )
        selectors.add_widget(self.table_field)
        selectors.add_widget(self.order_type_field)
        root.add_widget(selectors)

        self.actions = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=0,
            spacing=dp(8),
            opacity=0,
            disabled=True,
        )
        self.settle_btn = MDRaisedButton(
            text="Settle",
            md_bg_color=theme.THEME,
            size_hint_x=1,
            on_release=lambda *_: self._settle(),
        )
        self.actions.add_widget(self.settle_btn)
        root.add_widget(self.actions)

        self.status = MDLabel(
            text="Choose a table to start an order.",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            size_hint_y=None,
            height=dp(22),
        )
        root.add_widget(self.status)

        scroll = MDScrollView()
        body = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            size_hint_y=None,
            padding=(0, 0, 0, dp(16)),
        )
        body.bind(minimum_height=body.setter("height"))

        customer = MDCard(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(8),
            size_hint_y=None,
            height=dp(168),
            radius=[dp(14)],
            md_bg_color=theme.SURFACE,
            elevation=1,
        )
        customer.add_widget(
            MDLabel(
                text="Customer Details",
                bold=True,
                theme_text_color="Custom",
                text_color=theme.LOGIN_NAVY,
                size_hint_y=None,
                height=dp(24),
            )
        )
        self.customer_name = MDTextField(hint_text="Customer Name", text="")
        self.customer_mobile = MDTextField(hint_text="Mobile (10 digit)", text="", input_filter="int")
        customer.add_widget(self.customer_name)
        customer.add_widget(self.customer_mobile)
        body.add_widget(customer)

        self.search_field = MDTextField(
            hint_text="Search menu items by name or code…",
            size_hint_y=None,
            on_text_validate=lambda *_: self._search_add_first(),
        )
        body.add_widget(self.search_field)
        body.add_widget(
            MDRaisedButton(
                text="+ Add Items",
                md_bg_color=theme.THEME,
                size_hint_y=None,
                height=dp(40),
                on_release=lambda *_: self._search_add_first(),
            )
        )

        self.lines_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_y=None,
            padding=(0, dp(4), 0, dp(4)),
        )
        self.lines_box.bind(minimum_height=self.lines_box.setter("height"))
        body.add_widget(self.lines_box)

        bill = MDCard(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(4),
            size_hint_y=None,
            height=dp(168),
            radius=[dp(14)],
            md_bg_color=theme.SURFACE,
            elevation=1,
        )
        bill.add_widget(
            MDLabel(
                text="Bill Summary",
                bold=True,
                theme_text_color="Custom",
                text_color=theme.LOGIN_NAVY,
                size_hint_y=None,
                height=dp(24),
            )
        )
        self.subtotal_label = MDLabel(text="Subtotal  ₹0.00", size_hint_y=None, height=dp(20))
        self.cgst_label = MDLabel(text="CGST (2.5%)  ₹0.00", size_hint_y=None, height=dp(20))
        self.sgst_label = MDLabel(text="SGST (2.5%)  ₹0.00", size_hint_y=None, height=dp(20))
        self.total_label = MDLabel(
            text="Total  ₹0.00",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.THEME,
            size_hint_y=None,
            height=dp(28),
        )
        bill.add_widget(self.subtotal_label)
        bill.add_widget(self.cgst_label)
        bill.add_widget(self.sgst_label)
        bill.add_widget(self.total_label)
        body.add_widget(bill)

        self.notes_field = MDTextField(
            hint_text="Order notes (optional)",
            multiline=True,
            size_hint_y=None,
            height=dp(72),
        )
        body.add_widget(self.notes_field)

        scroll.add_widget(body)
        root.add_widget(scroll)

        footer = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(96), spacing=dp(8))
        self.kot_footer_btn = MDRaisedButton(
            text="SEND KOT",
            md_bg_color=theme.THEME,
            size_hint_x=1,
            opacity=0,
            disabled=True,
            on_release=lambda *_: self._save(kot=True),
        )
        footer.add_widget(self.kot_footer_btn)
        self.generate_footer_btn = MDFlatButton(
            text="Generate Invoice",
            theme_text_color="Custom",
            text_color=theme.THEME,
            size_hint_x=1,
            opacity=0.45,
            disabled=True,
            on_release=lambda *_: self._generate_invoice(),
        )
        footer.add_widget(self.generate_footer_btn)
        self.footer_box = footer
        root.add_widget(footer)
        self.add_widget(root)

    def on_workspace_enter(self) -> None:
        self._bootstrap()

    def _bootstrap(self) -> None:
        def work():
            floor = self.pos_api.floor()
            items = self.pos_api.menu_items()
            table = (self.table_field.text or "").strip()
            existing = self.pos_api.invoice_by_table(table) if table else None
            return floor, items, existing

        def ok(result):
            floor, items, existing = result
            self._menu = items
            tables = []
            for key in ("tables", "floor", "layout"):
                raw = floor.get(key) if isinstance(floor, dict) else None
                if isinstance(raw, list):
                    for t in raw:
                        if isinstance(t, dict):
                            label = t.get("label") or t.get("name") or t.get("id")
                            if label:
                                tables.append(str(label))
                        elif t:
                            tables.append(str(t))
            self._tables = tables
            if not (self.table_field.text or "").strip() and tables:
                self.table_field.text = tables[0]
            self._lines = []
            self._invoice_id = None
            self._invoice_generated = False
            if existing and isinstance(existing, dict):
                self._apply_invoice_dict(existing)
            self._render_lines()
            self.status.text = (
                f"{'Loaded invoice' if self._invoice_id else 'New order'} · "
                f"menu {len(items)} · tables {len(tables)}"
            )

        def err(exc):
            self.status.text = str(exc)
            toast(str(exc))

        run_async(work, ok, err)

    def _search_add_first(self) -> None:
        q = (self.search_field.text or "").strip().lower()
        if not q:
            toast("Type a menu name to add")
            return
        for item in self._menu:
            if q in item.name.lower():
                self._add_line(item)
                self.search_field.text = ""
                return
        toast("No menu match")

    def _add_line(self, item: MenuItem) -> None:
        for line in self._lines:
            if line.menu_id == item.id and line.name == item.name:
                line.qty += 1
                self._render_lines()
                return
        self._lines.append(
            InvoiceLine(
                uid=uuid.uuid4().hex[:8],
                name=item.name,
                rate=item.rate,
                qty=1,
                menu_id=item.id or None,
                variant=item.variant,
            )
        )
        self._render_lines()

    def _render_lines(self) -> None:
        self.lines_box.clear_widgets()
        if not self._lines:
            self.lines_box.add_widget(
                MDLabel(
                    text="No items added yet. Search and add menu items to begin billing.",
                    theme_text_color="Custom",
                    text_color=theme.TEXT_MUTED,
                    size_hint_y=None,
                    height=dp(48),
                )
            )
        else:
            for line in self._lines:
                amt = line.rate * line.qty
                self.lines_box.add_widget(
                    MDLabel(
                        text=f"{line.name}  ×{line.qty:g}  {_inr(line.rate)}  {_inr(amt)}",
                        size_hint_y=None,
                        height=dp(28),
                        theme_text_color="Custom",
                        text_color=theme.LOGIN_NAVY,
                    )
                )
        totals = calc_bill_totals(
            self._lines,
            discount_pct=self._discount_pct,
            service_pct=self._service_pct,
            tip=self._tip,
        )
        self.subtotal_label.text = f"Subtotal  {_inr(totals['subtotal'])}"
        self.cgst_label.text = f"CGST (2.5%)  {_inr(totals['cgst'])}"
        self.sgst_label.text = f"SGST (2.5%)  {_inr(totals['sgst'])}"
        self.total_label.text = f"Total  {_inr(totals['total'])}"
        self._sync_settle_visibility()

    def _pending_kot(self) -> bool:
        return has_pending_kot(self._lines)

    def _apply_invoice_dict(self, existing: dict) -> None:
        self._invoice_id = existing.get("id")
        self._invoice_generated = bool(
            existing.get("customer_bill_sent") or existing.get("customerBillSent")
        )
        self.customer_name.text = str(
            existing.get("customerName") or existing.get("customer_name") or ""
        )
        self.customer_mobile.text = str(
            existing.get("customerMobile") or existing.get("customer_mobile") or ""
        )[-10:]
        self.notes_field.text = str(existing.get("notes") or "")
        self._lines = []
        for line in existing.get("lines") or []:
            if not isinstance(line, dict):
                continue
            sent = line.get("kotSentQty")
            if sent is None:
                sent = line.get("kot_sent_qty")
            if sent is None:
                sent = line.get("sent_qty")
            self._lines.append(
                InvoiceLine(
                    uid=str(line.get("uid") or uuid.uuid4().hex[:8]),
                    name=str(line.get("name") or ""),
                    rate=float(line.get("rate") or 0),
                    qty=float(line.get("qty") or 1),
                    menu_id=line.get("menuId") or line.get("menu_id"),
                    variant=str(line.get("variant") or ""),
                    kot_sent_qty=float(sent or 0),
                )
            )

    def _sync_settle_visibility(self) -> None:
        has_lines = bool(self._lines)
        pending = self._pending_kot()
        show_settle = bool(self._invoice_generated and self._invoice_id and has_lines)
        show_generate = bool(not self._invoice_generated and has_lines and not pending)
        show_kot = bool(has_lines and pending)

        self.settle_btn.opacity = 1 if show_settle else 0
        self.settle_btn.disabled = not show_settle
        self.actions.height = dp(44) if show_settle else 0
        self.actions.opacity = 1 if show_settle else 0
        self.actions.disabled = not show_settle

        self.kot_footer_btn.opacity = 1 if show_kot else 0
        self.kot_footer_btn.disabled = not show_kot
        self.kot_footer_btn.height = dp(40) if show_kot else 0

        self.generate_footer_btn.disabled = not show_generate
        self.generate_footer_btn.opacity = 1 if show_generate else 0
        self.generate_footer_btn.height = dp(40) if show_generate else 0

        footer_h = 0
        if show_kot:
            footer_h += dp(48)
        if show_generate:
            footer_h += dp(48)
        if show_kot and show_generate:
            footer_h += dp(8)
        self.footer_box.height = footer_h if footer_h else 0
        self.footer_box.opacity = 1 if footer_h else 0
        self.footer_box.disabled = footer_h == 0

    def _save(self, *, kot: bool, customer_bill: bool = False) -> None:
        table = (self.table_field.text or "").strip()
        if not table:
            toast("Enter a table")
            return
        if not self._lines:
            toast("Add menu items first")
            return
        if kot and not self._pending_kot():
            toast("Nothing new to send — kitchen is already up to date")
            self._sync_settle_visibility()
            return
        order_no = f"MOB-{time.strftime('%y%m%d')}-{uuid.uuid4().hex[:4].upper()}"
        payload = build_invoice_payload(
            order_no=order_no,
            table=table,
            lines=self._lines,
            order_type=(self.order_type_field.text or "dine_in").strip() or "dine_in",
            customer_name=(self.customer_name.text or "").strip() or "Guest",
            customer_mobile=(self.customer_mobile.text or "").strip(),
            notes=(self.notes_field.text or "").strip(),
            kot_send=kot,
            customer_bill=customer_bill,
            invoice_id=self._invoice_id,
            discount_pct=self._discount_pct,
            service_pct=self._service_pct,
            tip=self._tip,
        )

        def work():
            saved = self.pos_api.save_invoice(payload)
            invoice_id = None
            inv = {}
            if isinstance(saved, dict):
                inv = saved.get("invoice") or {}
                invoice_id = inv.get("id") or self._invoice_id
            still_pending = False
            for row in (inv.get("lines") or []):
                qty = float(row.get("qty") or 0)
                sent = float(
                    row.get("sent_qty")
                    if row.get("sent_qty") is not None
                    else (row.get("kotSentQty") or 0)
                )
                if qty > sent + 1e-9:
                    still_pending = True
                    break
            # Dedicated send-kot only when save left unsent qty (or omitted lines).
            if kot and invoice_id and (still_pending or not (inv.get("lines") or [])):
                kot_result = self.pos_api.send_kot(int(invoice_id))
                return saved, kot_result
            return saved, None

        def ok(payload):
            saved, kot_result = payload
            inv = (saved or {}).get("invoice") or {}
            if kot_result and isinstance(kot_result.get("invoice"), dict):
                inv = kot_result["invoice"] or inv
            self._invoice_id = inv.get("id") or self._invoice_id
            if customer_bill:
                self._invoice_generated = True
            elif inv.get("customer_bill_sent") is not None or inv.get("customerBillSent") is not None:
                self._invoice_generated = bool(inv.get("customer_bill_sent") or inv.get("customerBillSent"))
            if inv.get("lines"):
                self._apply_invoice_dict(inv)
            elif kot:
                # Mark all local lines as fully sent when server omitted lines.
                for line in self._lines:
                    line.kot_sent_qty = float(line.qty or 0)
            toast("Invoice generated" if customer_bill else ("KOT sent" if kot else "Held"))
            label = "Bar" if getattr(self, "outlet", "restaurant") == "bar" else "Restaurant"
            self.status.text = (
                f"KOT sent · {label} · #{self._invoice_id}"
                if kot
                else f"Saved invoice {self._invoice_id}"
            )
            self._render_lines()

        def err(exc):
            toast(str(exc))

        run_async(work, ok, err)

    def _generate_invoice(self) -> None:
        if not (self.customer_name.text or "").strip():
            toast("Enter customer name before generating the invoice")
            return
        if self._pending_kot():
            toast("Send all items to the kitchen (KOT) before generating the invoice")
            return
        self._save(kot=False, customer_bill=True)

    def _settle(self) -> None:
        if not self._invoice_generated or not self._invoice_id:
            toast("Generate the invoice before settle")
            return
        totals = calc_bill_totals(
            self._lines,
            discount_pct=self._discount_pct,
            service_pct=self._service_pct,
            tip=self._tip,
        )

        def work():
            return self.pos_api.settle(
                int(self._invoice_id),
                {
                    "method": "cash",
                    "payment_splits": [{"method": "cash", "amount": totals["total"]}],
                },
            )

        def ok(_data):
            toast("Settled")
            self._lines = []
            self._invoice_id = None
            self._invoice_generated = False
            self._render_lines()
            self.status.text = "Settled · ready for next order"

        def err(exc):
            toast(str(exc))

        run_async(work, ok, err)
