"""Tips analytics summary + add tip."""

from __future__ import annotations

from kivy.metrics import dp
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from hbe_mobile import theme
from hbe_mobile.api import payroll as payroll_api
from hbe_mobile.utils.async_jobs import run_async


class PayrollTipsScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "payroll_tips"
        self.md_bg_color = theme.BG
        self._outlet = "Hotel"

        root = MDBoxLayout(orientation="vertical", padding=dp(14), spacing=dp(8))
        root.add_widget(MDLabel(text="Tips", font_style="H4", bold=True, theme_text_color="Custom", text_color=theme.TEXT, size_hint_y=None, height=dp(36)))
        self.status = MDLabel(text="Loading…", theme_text_color="Custom", text_color=theme.TEXT_MUTED, size_hint_y=None, height=dp(22))
        root.add_widget(self.status)
        scroll = MDScrollView()
        self.list_box = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)

        form = MDBoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(220))
        chips = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(4))
        for loc in ("Hotel", "Bar", "Restaurant"):
            chips.add_widget(MDFlatButton(text=loc, theme_text_color="Custom", text_color=theme.THEME, on_release=lambda *_a, v=loc: self._set_outlet(v)))
        self.emp_field = MDTextField(hint_text="Employee ID", size_hint_y=None, height=dp(44))
        self.amount_field = MDTextField(hint_text="Amount", size_hint_y=None, height=dp(44))
        self.date_field = MDTextField(hint_text="Date YYYY-MM-DD", text=payroll_api.today_iso(), size_hint_y=None, height=dp(44))
        form.add_widget(chips)
        form.add_widget(self.emp_field)
        form.add_widget(self.amount_field)
        form.add_widget(MDRaisedButton(text="Send", md_bg_color=theme.THEME, on_release=lambda *_: self._save()))
        root.add_widget(form)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        self._reload()

    def _set_outlet(self, value):
        self._outlet = value

    def _reload(self):
        def work():
            return payroll_api.fetch_tips(self.app.api)

        def ok(data):
            self.status.text = f"Total {data.get('grand_total') or 0}"
            self.list_box.clear_widgets()
            for row in data.get("top_employees") or []:
                card = MDCard(orientation="vertical", padding=dp(12), size_hint_y=None, height=dp(56), md_bg_color=theme.SURFACE, radius=[dp(12)])
                card.add_widget(MDLabel(text=str(row.get("employee_name") or ""), bold=True, size_hint_y=None, height=dp(20)))
                card.add_widget(MDLabel(text=f"₹{row.get('total') or 0}", font_style="Caption", size_hint_y=None, height=dp(18)))
                self.list_box.add_widget(card)
            if not data.get("top_employees"):
                self.list_box.add_widget(MDLabel(text="No tips in this range.", size_hint_y=None, height=dp(28)))

        def err(exc):
            self.status.text = str(getattr(exc, "message", exc) or exc)

        run_async(work, ok, err)

    def _save(self):
        payload = {
            "employee_id": (self.emp_field.text or "").strip(),
            "amount": (self.amount_field.text or "").strip(),
            "date": (self.date_field.text or "").strip() or payroll_api.today_iso(),
            "location": self._outlet,
            "company": "HBE",
            "description": "",
        }
        err = payroll_api.validate_tip_payload(payload["employee_id"], payload["amount"], payload["location"])
        if err:
            toast(err)
            return

        def work():
            return payroll_api.add_tip(self.app.api, payload)

        def ok(_data):
            toast("Saved")
            self.amount_field.text = ""
            self._reload()

        def fail(exc):
            toast(str(getattr(exc, "message", exc) or exc))

        run_async(work, ok, fail)
