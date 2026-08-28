"""Credit dashboard + add credit/repayment."""

from __future__ import annotations

from kivy.metrics import dp
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDFlatButton, MDRoundFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from hbe_mobile import theme
from hbe_mobile.api import payroll as payroll_api
from hbe_mobile.utils.async_jobs import run_async

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def _format_display_date(iso: str) -> str:
    parts = (iso or "")[:10].split("-")
    if len(parts) != 3:
        return iso or "Select date…"
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{d:02d} {_MONTHS[m - 1]} {y}"
    except Exception:
        return iso or "Select date…"


def _money(value) -> str:
    try:
        return f"₹{float(value or 0):,.2f}"
    except Exception:
        return str(value or "0")


def _format_period(iso: str) -> str:
    parts = (iso or "")[:10].split("-")
    if len(parts) < 2:
        return "Select period…"
    try:
        y, m = int(parts[0]), int(parts[1])
        return f"{_MONTHS[m - 1]} {y}"
    except Exception:
        return "Select period…"


class PayrollCreditScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "payroll_credit"
        self.md_bg_color = (0.957, 0.969, 0.984, 1)
        self._txn = "credit"
        self._pay = "cash"
        self._period_iso = payroll_api.today_iso()
        self._entry_iso = payroll_api.today_iso()

        root = MDBoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        root.add_widget(MDLabel(
            text="Credit", font_style="H5", bold=True,
            theme_text_color="Custom", text_color=theme.TEXT,
            size_hint_y=None, height=dp(32),
        ))

        period_col = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(68), spacing=dp(2))
        period_col.add_widget(MDLabel(
            text="PERIOD", font_style="Caption", bold=True,
            theme_text_color="Custom", text_color=(0.58, 0.64, 0.72, 1),
            size_hint_y=None, height=dp(16),
        ))
        self.period_btn = MDRoundFlatButton(
            text=_format_period(self._period_iso),
            theme_text_color="Custom", text_color=theme.TEXT,
            line_color=(0.89, 0.91, 0.94, 1), md_bg_color=(1, 1, 1, 1),
            size_hint_x=1, size_hint_y=None, height=dp(46),
        )
        self.period_btn.bind(on_release=lambda *_: self._open_picker("period"))
        period_col.add_widget(self.period_btn)
        root.add_widget(period_col)

        self.status = MDLabel(
            text="Loading…", theme_text_color="Custom", text_color=theme.TEXT_MUTED,
            size_hint_y=None, height=dp(20), font_style="Caption",
        )
        root.add_widget(self.status)

        scroll = MDScrollView()
        self.list_box = MDBoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None, padding=(0, 4, 0, 12))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)

        form = MDBoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(300))
        form.add_widget(MDLabel(text="Advance / Credit", bold=True, size_hint_y=None, height=dp(22)))
        self.emp_field = MDTextField(hint_text="Employee ID", size_hint_y=None, height=dp(44))
        self.date_btn = MDRoundFlatButton(
            text=_format_display_date(self._entry_iso),
            theme_text_color="Custom", text_color=theme.TEXT,
            line_color=(0.89, 0.91, 0.94, 1), md_bg_color=(1, 1, 1, 1),
            size_hint_x=1, size_hint_y=None, height=dp(44),
        )
        self.date_btn.bind(on_release=lambda *_: self._open_picker("entry"))
        self.amount_field = MDTextField(hint_text="Amount", size_hint_y=None, height=dp(44))
        self.desc_field = MDTextField(hint_text="Description", size_hint_y=None, height=dp(44))
        self.txn_field = MDTextField(hint_text="Transaction ID (bank)", size_hint_y=None, height=dp(44))
        chips = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        self.btn_credit = MDRaisedButton(text="Advance/Credit", md_bg_color=theme.THEME, on_release=lambda *_: self._set_txn("credit"))
        self.btn_repay = MDFlatButton(text="Repayment", theme_text_color="Custom", text_color=theme.THEME, on_release=lambda *_: self._set_txn("repayment"))
        chips.add_widget(self.btn_credit)
        chips.add_widget(self.btn_repay)
        pay = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        self.btn_cash = MDRaisedButton(text="Cash", md_bg_color=theme.THEME, on_release=lambda *_: self._set_pay("cash"))
        self.btn_bank = MDFlatButton(text="Bank", theme_text_color="Custom", text_color=theme.THEME, on_release=lambda *_: self._set_pay("bank_transfer"))
        pay.add_widget(self.btn_cash)
        pay.add_widget(self.btn_bank)
        send = MDRaisedButton(text="Send", md_bg_color=theme.THEME, size_hint_y=None, height=dp(44), on_release=lambda *_: self._save())
        for w in (self.emp_field, self.date_btn, self.desc_field, self.amount_field, chips, pay, self.txn_field, send):
            form.add_widget(w)
        root.add_widget(form)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        self._reload()

    def _set_txn(self, value):
        self._txn = value

    def _set_pay(self, value):
        self._pay = value

    def _open_picker(self, kind):
        try:
            from kivymd.uix.pickers import MDDatePicker
        except Exception:
            toast("Date picker unavailable")
            return
        iso = self._period_iso if kind == "period" else self._entry_iso
        parts = (iso or payroll_api.today_iso())[:10].split("-")
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        except Exception:
            from datetime import date as _date
            today = _date.today()
            y, m, d = today.year, today.month, today.day
        picker = MDDatePicker(year=y, month=m, day=d)
        picker.bind(on_save=lambda p, v, r, k=kind: self._on_date_save(k, v))
        picker.open()

    def _on_date_save(self, kind, value):
        try:
            iso = value.isoformat()
        except Exception:
            iso = str(value)[:10]
        if kind == "period":
            self._period_iso = iso
            self.period_btn.text = _format_period(iso)
            self._reload()
        else:
            self._entry_iso = iso
            self.date_btn.text = _format_display_date(iso)

    def _reload(self):
        parts = (self._period_iso or payroll_api.today_iso())[:10].split("-")
        year, month = parts[0], str(int(parts[1]))

        def work():
            return payroll_api.fetch_credits(self.app.api, year=year, month=month)

        def ok(data):
            st = data.get("payroll_state") or {}
            self.status.text = (st.get("label") or "") + (" · Locked" if st.get("locked") else "")
            self.list_box.clear_widgets()
            self.list_box.add_widget(MDLabel(
                text=f"Total {_money(data.get("total_credit_amount"))}",
                bold=True, size_hint_y=None, height=dp(22),
            ))
            for row in data.get("employees") or []:
                if float(row.get("credit_balance") or 0) == 0:
                    continue
                card = MDCard(
                    orientation="vertical", padding=dp(12), size_hint_y=None, height=dp(84),
                    md_bg_color=(1, 1, 1, 1), radius=[dp(16)],
                )
                card.add_widget(MDLabel(text=str(row.get("name") or ""), bold=True, size_hint_y=None, height=dp(22)))
                card.add_widget(MDLabel(
                    text=f"{row.get("emp_code") or ""} · {row.get("location") or "—"}",
                    font_style="Caption", theme_text_color="Custom", text_color=theme.TEXT_MUTED,
                    size_hint_y=None, height=dp(18),
                ))
                card.add_widget(MDLabel(
                    text=str(_money(row.get("credit_balance"))),
                    bold=True, theme_text_color="Custom", text_color=theme.THEME,
                    size_hint_y=None, height=dp(20),
                ))
                self.list_box.add_widget(card)

        def err(exc):
            self.status.text = str(getattr(exc, "message", exc) or exc)

        run_async(work, ok, err)

    def _save(self):
        payload = {
            "employee_id": (self.emp_field.text or "").strip(),
            "date": self._entry_iso,
            "description": (self.desc_field.text or "").strip() or "Advance",
            "amount": (self.amount_field.text or "").strip(),
            "transaction_type": self._txn,
            "payment_type": self._pay,
            "transaction_id": (self.txn_field.text or "").strip(),
        }

        def work():
            return payroll_api.add_credit(self.app.api, payload)

        def ok(_data):
            toast("Saved")
            self._reload()

        def fail(exc):
            toast(str(getattr(exc, "message", exc) or exc))

        run_async(work, ok, fail)
