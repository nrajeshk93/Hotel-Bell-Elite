"""Indent Request — create a stores indent (draft or send for approval)."""

from __future__ import annotations

from kivy.metrics import dp
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from hbe_mobile import theme
from hbe_mobile.api import indent_request as indent_api
from hbe_mobile.utils.async_jobs import run_async


def _inr(value: float) -> str:
    return f"₹{value:,.2f}"


class IndentRequestScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "indent_request"
        self.md_bg_color = theme.BG
        self._outlet = "restaurant"
        self._busy = False
        self._products: list[dict] = []
        self._lines: list[dict] = []
        self._picked: dict | None = None
        self._pack_index = 0
        self._pack_options: list[dict] = []

        root = MDBoxLayout(
            orientation="vertical",
            padding=[dp(14), dp(12), dp(14), dp(8)],
            spacing=dp(8),
        )
        root.add_widget(
            MDLabel(
                text="Indent Request",
                font_style="H4",
                bold=True,
                theme_text_color="Custom",
                text_color=theme.TEXT,
                size_hint_y=None,
                height=dp(36),
            )
        )

        chips = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8))
        self.btn_restaurant = MDRaisedButton(
            text="Restaurant",
            md_bg_color=theme.ACCENT,
            on_release=lambda *_: self._set_outlet("restaurant"),
        )
        self.btn_bar = MDFlatButton(
            text="Bar",
            theme_text_color="Custom",
            text_color=theme.ACCENT,
            on_release=lambda *_: self._set_outlet("bar"),
        )
        chips.add_widget(self.btn_restaurant)
        chips.add_widget(self.btn_bar)
        root.add_widget(chips)

        self.status = MDLabel(
            text="Loading…",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            size_hint_y=None,
            height=dp(22),
        )
        root.add_widget(self.status)

        self.search = MDTextField(
            hint_text="Search product…",
            helper_text="Item",
            helper_text_mode="on_focus",
            size_hint_y=None,
            height=dp(52),
        )
        self.search.bind(text=lambda *_: self._filter_products())
        root.add_widget(self.search)

        self.suggest = MDBoxLayout(
            orientation="vertical",
            spacing=dp(4),
            size_hint_y=None,
            height=dp(0),
        )
        self.suggest.bind(minimum_height=self.suggest.setter("height"))
        root.add_widget(self.suggest)

        composer = MDBoxLayout(orientation="vertical", spacing=dp(4), size_hint_y=None, height=dp(120))
        self.pack_btn = MDFlatButton(
            text="Base unit",
            theme_text_color="Custom",
            text_color=theme.ACCENT,
            on_release=lambda *_: self._cycle_pack(),
        )
        composer.add_widget(self.pack_btn)
        qty_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8))
        self.qty_field = MDTextField(hint_text="Qty", text="1", input_filter="float", size_hint_x=0.3)
        self.unit_field = MDTextField(hint_text="Unit", text="kg", size_hint_x=0.3, readonly=False)
        self.price_field = MDTextField(hint_text="Price/qty", text="", input_filter="float", size_hint_x=0.4)
        qty_row.add_widget(self.qty_field)
        qty_row.add_widget(self.unit_field)
        qty_row.add_widget(self.price_field)
        composer.add_widget(qty_row)
        composer.add_widget(
            MDRaisedButton(
                text="Add item",
                md_bg_color=theme.ACCENT,
                on_release=lambda *_: self._add_line(),
            )
        )
        root.add_widget(composer)

        scroll = MDScrollView()
        self.list_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(8),
            size_hint_y=None,
            padding=(0, 0, 0, dp(12)),
        )
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)

        self.notes = MDTextField(
            hint_text="Notes",
            helper_text="Anything the approver should know.",
            helper_text_mode="on_focus",
            size_hint_y=None,
            height=dp(52),
        )
        root.add_widget(self.notes)

        self.total_label = MDLabel(
            text="Total  ₹0.00",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.TEXT,
            size_hint_y=None,
            height=dp(24),
        )
        root.add_widget(self.total_label)

        sticky = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        sticky.add_widget(
            MDFlatButton(
                text="Draft",
                theme_text_color="Custom",
                text_color=theme.ACCENT,
                on_release=lambda *_: self._submit("save"),
            )
        )
        sticky.add_widget(
            MDRaisedButton(
                text="Send for Approval",
                md_bg_color=theme.ACCENT,
                on_release=lambda *_: self._submit("submit"),
            )
        )
        root.add_widget(sticky)
        self.add_widget(root)

    def on_workspace_enter(self) -> None:
        self._load_catalog()

    def _set_outlet(self, outlet: str) -> None:
        next_outlet = "bar" if outlet == "bar" else "restaurant"
        if next_outlet == self._outlet and self._products:
            return
        self._outlet = next_outlet
        if self._outlet == "restaurant":
            self.btn_restaurant.md_bg_color = theme.ACCENT
            self.btn_bar.md_bg_color = (0, 0, 0, 0)
        else:
            self.btn_bar.md_bg_color = theme.ACCENT
            self.btn_restaurant.md_bg_color = (0, 0, 0, 0)
        self._lines = []
        self._picked = None
        self._pack_options = []
        self._pack_index = 0
        self.search.text = ""
        self._render_lines()
        self._load_catalog()

    def _load_catalog(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.status.text = "Loading…"
        outlet = self._outlet

        def work():
            return indent_api.fetch_catalog(self.app.api, outlet)

        def ok(data):
            self._busy = False
            self._products = indent_api.flatten_catalog(data)
            self.status.text = f"{len(self._products)} products"
            self._filter_products()

        def err(exc):
            self._busy = False
            self.status.text = str(getattr(exc, "message", None) or exc)
            toast(self.status.text)

        run_async(work, on_success=ok, on_error=err)

    def _filter_products(self) -> None:
        query = (self.search.text or "").strip().lower()
        self.suggest.clear_widgets()
        if not query:
            self.suggest.height = 0
            return
        matches = []
        for product in self._products:
            name = str(product.get("name") or "")
            cat = str(product.get("category_name") or "")
            hay = f"{name} {cat}".lower()
            if query in hay:
                matches.append(product)
            if len(matches) >= 8:
                break
        for product in matches:
            name = str(product.get("name") or "")
            cat = str(product.get("category_name") or "")
            unit = str(product.get("default_unit") or "")
            price = product.get("approximate_price_display") or product.get("approximate_price") or ""
            label = MDFlatButton(
                text=f"{name}  ·  {cat}  ·  {unit}  ·  {price}",
                theme_text_color="Custom",
                text_color=theme.TEXT,
                on_release=lambda *_a, p=product: self._pick_product(p),
            )
            self.suggest.add_widget(label)
        self.suggest.height = dp(36 * max(len(matches), 0))

    def _pick_product(self, product: dict) -> None:
        self._picked = product
        self.search.text = str(product.get("name") or "")
        self.suggest.clear_widgets()
        self.suggest.height = 0
        variants = list(product.get("variants") or [])
        self._pack_options = [{"label": "Base unit", "qty_in_base": None, "approximate_price": product.get("approximate_price")}]
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            label = str(variant.get("label") or "").strip()
            if not label:
                continue
            self._pack_options.append(variant)
        self._pack_index = 1 if len(self._pack_options) > 1 else 0
        self.unit_field.text = str(product.get("default_unit") or "kg")
        self.qty_field.text = "1"
        self._apply_pack()

    def _cycle_pack(self) -> None:
        if len(self._pack_options) <= 1:
            return
        self._pack_index = (self._pack_index + 1) % len(self._pack_options)
        self._apply_pack()

    def _apply_pack(self) -> None:
        if not self._pack_options:
            self.pack_btn.text = "Base unit"
            self.unit_field.readonly = False
            return
        pack = self._pack_options[self._pack_index]
        label = str(pack.get("label") or "Base unit")
        self.pack_btn.text = label
        price = pack.get("approximate_price")
        if price in (None, ""):
            price = (self._picked or {}).get("approximate_price")
        self.price_field.text = "" if price in (None, "") else str(price)
        locked = label != "Base unit"
        self.unit_field.readonly = locked
        if not locked and self._picked:
            self.unit_field.text = str(self._picked.get("default_unit") or self.unit_field.text or "kg")

    def _add_line(self) -> None:
        product = self._picked
        if not product:
            toast("Search product…")
            return
        pack = self._pack_options[self._pack_index] if self._pack_options else {}
        pack_label = str(pack.get("label") or "")
        if pack_label == "Base unit":
            pack_label = ""
            pack_qty = None
        else:
            try:
                pack_qty = float(pack.get("qty_in_base") or 0) or None
            except (TypeError, ValueError):
                pack_qty = None
        try:
            qty = float(self.qty_field.text or 0)
        except (TypeError, ValueError):
            qty = 0
        try:
            price = float(self.price_field.text or 0)
        except (TypeError, ValueError):
            price = 0
        line = {
            "item_name": str(product.get("name") or "").strip(),
            "quantity": qty,
            "unit": (self.unit_field.text or "pcs").strip() or "pcs",
            "approximate_price": price,
            "pack_label": pack_label,
            "pack_qty_in_base": pack_qty,
        }
        error = indent_api.validate_lines([line])
        if error:
            toast(error)
            return
        self._lines.append(line)
        self._picked = None
        self.search.text = ""
        self.qty_field.text = "1"
        self.price_field.text = ""
        self.pack_btn.text = "Base unit"
        self._pack_options = []
        self._pack_index = 0
        self.unit_field.readonly = False
        self._render_lines()

    def _remove_line(self, index: int) -> None:
        if 0 <= index < len(self._lines):
            self._lines.pop(index)
            self._render_lines()

    def _render_lines(self) -> None:
        self.list_box.clear_widgets()
        running = 0.0
        if not self._lines:
            self.list_box.add_widget(
                MDLabel(
                    text="No items yet",
                    theme_text_color="Secondary",
                    size_hint_y=None,
                    height=dp(32),
                )
            )
        for idx, line in enumerate(self._lines):
            total = indent_api.line_total(line.get("quantity"), line.get("approximate_price"))
            running += total
            pack = str(line.get("pack_label") or "Base unit")
            card = MDCard(
                orientation="vertical",
                padding=dp(10),
                spacing=dp(2),
                size_hint_y=None,
                height=dp(110),
                radius=[12, 12, 12, 12],
                md_bg_color=theme.SURFACE,
            )
            card.add_widget(
                MDLabel(
                    text=str(line.get("item_name") or ""),
                    bold=True,
                    theme_text_color="Custom",
                    text_color=theme.TEXT,
                    size_hint_y=None,
                    height=dp(22),
                )
            )
            card.add_widget(
                MDLabel(
                    text=(
                        f"Pack {pack}  ·  Qty {line.get('quantity')}  ·  "
                        f"Unit {line.get('unit')}  ·  Price/qty {_inr(float(line.get('approximate_price') or 0))}"
                    ),
                    theme_text_color="Custom",
                    text_color=theme.TEXT_MUTED,
                    size_hint_y=None,
                    height=dp(20),
                )
            )
            row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36))
            row.add_widget(
                MDLabel(
                    text=f"Total  {_inr(total)}",
                    bold=True,
                    theme_text_color="Custom",
                    text_color=theme.TEXT,
                )
            )
            row.add_widget(
                MDFlatButton(
                    text="Remove",
                    theme_text_color="Custom",
                    text_color=theme.DANGER,
                    on_release=lambda *_a, i=idx: self._remove_line(i),
                )
            )
            card.add_widget(row)
            self.list_box.add_widget(card)
        self.total_label.text = f"Total  {_inr(running)}"

    def _submit(self, action: str) -> None:
        if self._busy:
            return
        error = indent_api.validate_lines(self._lines)
        if error:
            toast(error)
            return
        self._busy = True
        self.status.text = "Sending…" if action == "submit" else "Saving…"
        outlet = self._outlet
        notes = self.notes.text or ""
        lines = list(self._lines)

        def work():
            return indent_api.submit_indent(
                self.app.api,
                outlet=outlet,
                notes=notes,
                action=action,
                lines=lines,
            )

        def ok(data):
            self._busy = False
            if action == "submit":
                toast("Indent sent for approval")
            else:
                toast("Indent saved as draft")
            self._lines = []
            self.notes.text = ""
            self._render_lines()
            code = str((data or {}).get("indent_no") or "")
            self.status.text = code or "Saved"

        def err(exc):
            self._busy = False
            self.status.text = str(getattr(exc, "message", None) or exc)
            toast(self.status.text)

        run_async(work, on_success=ok, on_error=err)
