"""Products — list via products-lite; create via product-master form POST."""

from __future__ import annotations

from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.list import MDList, OneLineAvatarIconListItem, IconLeftWidget
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField
from kivymd.toast import toast

from hbe_mobile import theme
from hbe_mobile.api import products as products_api
from hbe_mobile.utils.async_jobs import run_async


class ProductsScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "products"
        self.md_bg_color = theme.BG
        self._categories: list[tuple[str, str]] = []
        self._dialog = None

        root = MDBoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        bar = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        self.search = MDTextField(hint_text="Search products", size_hint_x=0.7)
        bar.add_widget(self.search)
        bar.add_widget(
            MDRaisedButton(text="Search", md_bg_color=theme.THEME, on_release=lambda *_: self.refresh())
        )
        bar.add_widget(
            MDRaisedButton(text="Add", md_bg_color=theme.ACCENT, on_release=lambda *_: self._open_add())
        )
        root.add_widget(bar)
        self.status = MDLabel(text="", size_hint_y=None, height=dp(24), theme_text_color="Secondary")
        root.add_widget(self.status)

        scroll = MDScrollView()
        self.list = MDList()
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_workspace_enter(self) -> None:
        self.refresh()
        self._load_categories()

    def refresh(self) -> None:
        q = (self.search.text or "").strip()

        def work():
            return products_api.list_products(self.app.api, q=q, outlet="all")

        def ok(products):
            self.list.clear_widgets()
            self.status.text = f"{len(products)} products"
            for p in products:
                price = f" · ₹{p.approximate_price:g}" if p.approximate_price is not None else ""
                text = f"{p.name} ({p.outlet or '—'}){price}"
                item = OneLineAvatarIconListItem(text=text)
                item.add_widget(IconLeftWidget(icon="package-variant"))
                self.list.add_widget(item)

        def err(exc):
            self.status.text = str(exc)
            toast(str(exc))

        run_async(work, ok, err)

    def _load_categories(self) -> None:
        def work():
            return products_api.list_categories(self.app.api)

        def ok(cats):
            self._categories = cats

        def err(_exc):
            self._categories = []

        run_async(work, ok, err)

    def _open_add(self) -> None:
        if self._dialog:
            return
        content = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None, height=dp(220))
        name_f = MDTextField(hint_text="Product name")
        cat_f = MDTextField(
            hint_text="Category id",
            helper_text="From Product Master categories",
            helper_text_mode="on_focus",
            text=self._categories[0][0] if self._categories else "",
        )
        outlet_f = MDTextField(hint_text="Outlet (restaurant|bar|both)", text="restaurant")
        unit_f = MDTextField(hint_text="Unit", text="kg")
        price_f = MDTextField(hint_text="Approx price", text="0")
        for w in (name_f, cat_f, outlet_f, unit_f, price_f):
            content.add_widget(w)

        def save(*_a):
            self._dialog.dismiss()
            self._dialog = None

            def work():
                products_api.save_product(
                    self.app.api,
                    name=name_f.text.strip(),
                    category_id=cat_f.text.strip(),
                    outlet=outlet_f.text.strip().lower(),
                    unit=unit_f.text.strip() or "kg",
                    approximate_price=price_f.text.strip() or "0",
                )
                return True

            def ok(_):
                toast("Product saved")
                self.refresh()

            def err(exc):
                toast(str(exc))

            run_async(work, ok, err)

        self._dialog = MDDialog(
            title="Add product",
            type="custom",
            content_cls=content,
            buttons=[
                MDFlatButton(text="Cancel", on_release=lambda *_: self._close_dialog()),
                MDRaisedButton(text="Save", md_bg_color=theme.THEME, on_release=save),
            ],
        )
        self._dialog.open()

    def _close_dialog(self) -> None:
        if self._dialog:
            self._dialog.dismiss()
            self._dialog = None
