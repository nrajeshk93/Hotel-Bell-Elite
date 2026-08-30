"""Employee list, detail, and simple add."""

from __future__ import annotations

from kivy.metrics import dp
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton, MDRoundFlatButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from hbe_mobile import theme

def _style_md_date_picker(picker):
    """Force MDDatePicker chrome to theme.ACCENT (#1877F2)."""
    for attr, val in (
        ("primary_color", theme.ACCENT),
        ("accent_color", theme.ACCENT),
        ("selector_color", theme.ACCENT),
        ("text_button_color", theme.ACCENT),
    ):
        try:
            setattr(picker, attr, val)
        except Exception:
            pass
    try:
        picker.firstweekday = 0  # Sunday
    except Exception:
        pass
    return picker
from hbe_mobile.api import payroll as payroll_api
from hbe_mobile.utils.async_jobs import run_async

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


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


class PayrollEmployeesScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "payroll_employees"
        self.md_bg_color = (0.957, 0.969, 0.984, 1)
        self._busy = False
        self._reload_ev = None
        self._period_iso = payroll_api.today_iso()

        root = MDBoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
        root.add_widget(MDLabel(
            text="Employee", font_style="H5", bold=True,
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
        self.period_btn.bind(on_release=lambda *_: self._open_period_picker())
        period_col.add_widget(self.period_btn)
        root.add_widget(period_col)

        self.search = MDTextField(
            hint_text="Search name, code, mobile…", size_hint_y=None, height=dp(48)
        )
        self.search.bind(text=lambda *_: self._queue_reload())
        root.add_widget(self.search)

        self.status = MDLabel(
            text="Loading…", theme_text_color="Custom", text_color=theme.TEXT_MUTED,
            size_hint_y=None, height=dp(20), font_style="Caption",
        )
        root.add_widget(self.status)

        scroll = MDScrollView()
        self.list_box = MDBoxLayout(
            orientation="vertical", spacing=dp(10), size_hint_y=None, padding=(0, 4, 0, 12)
        )
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)

        add = MDBoxLayout(orientation="vertical", spacing=dp(6), size_hint_y=None, height=dp(230))
        add.add_widget(MDLabel(text="Add employee", bold=True, size_hint_y=None, height=dp(22)))
        self.name_field = MDTextField(hint_text="Name", size_hint_y=None, height=dp(44))
        self.mobile_field = MDTextField(hint_text="10-digit mobile", size_hint_y=None, height=dp(44))
        self.location_field = MDTextField(hint_text="Location", size_hint_y=None, height=dp(44))
        self.salary_field = MDTextField(hint_text="Gross salary", size_hint_y=None, height=dp(44))
        for w in (self.name_field, self.mobile_field, self.location_field, self.salary_field):
            add.add_widget(w)
        add.add_widget(MDRaisedButton(
            text="Add", md_bg_color=theme.ACCENT, size_hint_y=None, height=dp(44),
            on_release=lambda *_: self._add(),
        ))
        root.add_widget(add)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        self._reload()

    def _open_period_picker(self):
        try:
            from kivymd.uix.pickers import MDDatePicker
        except Exception:
            toast("Date picker unavailable")
            return
        parts = (self._period_iso or payroll_api.today_iso())[:10].split("-")
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        except Exception:
            from datetime import date as _date
            today = _date.today()
            y, m, d = today.year, today.month, today.day
        picker = _style_md_date_picker(MDDatePicker(year=y, month=m, day=d))
        picker.bind(on_save=self._on_period_save)
        picker.open()

    def _on_period_save(self, _picker, value, _date_range):
        try:
            self._period_iso = value.isoformat()
        except Exception:
            self._period_iso = str(value)[:10]
        self.period_btn.text = _format_period(self._period_iso)
        self._reload()

    def _queue_reload(self):
        from kivy.clock import Clock
        if self._reload_ev:
            self._reload_ev.cancel()
        self._reload_ev = Clock.schedule_once(lambda *_: self._reload(), 0.3)

    def _reload(self):
        if self._busy:
            return
        self._busy = True
        parts = (self._period_iso or payroll_api.today_iso())[:10].split("-")
        year, month = parts[0], str(int(parts[1]))
        q = (self.search.text or "").strip()

        def work():
            return payroll_api.fetch_employees(
                self.app.api, q=q, status="active", year=year, month=month
            )

        def ok(data):
            self._busy = False
            st = data.get("payroll_state") or {}
            emps = data.get("employees") or []
            self.status.text = f"{len(emps)} employees" + (
                f" · {st.get('label')}" if st.get("label") else ""
            ) + (" · Locked" if st.get("locked") else "")
            self.list_box.clear_widgets()
            for row in emps:
                card = MDCard(
                    orientation="vertical", padding=dp(12), size_hint_y=None, height=dp(88),
                    md_bg_color=(1, 1, 1, 1), radius=[dp(16)],
                )
                top = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
                top.add_widget(MDLabel(
                    text=str(row.get("name") or ""), bold=True, size_hint_y=None, height=dp(22),
                ))
                top.add_widget(MDLabel(
                    text=_money(row.get("gross_salary")), bold=True,
                    theme_text_color="Custom", text_color=theme.ACCENT,
                    halign="right", size_hint_y=None, height=dp(22),
                ))
                card.add_widget(top)
                card.add_widget(MDLabel(
                    text=f"{row.get('emp_code') or ''} · {row.get('location') or '—'} · {row.get('mobile') or ''}",
                    font_style="Caption", theme_text_color="Custom", text_color=theme.TEXT_MUTED,
                    size_hint_y=None, height=dp(18),
                ))
                card.add_widget(MDLabel(
                    text=str(row.get("status") or "active"),
                    font_style="Caption", theme_text_color="Custom", text_color=theme.TEXT_MUTED,
                    size_hint_y=None, height=dp(18),
                ))
                self.list_box.add_widget(card)

        def err(exc):
            self._busy = False
            self.status.text = str(getattr(exc, "message", exc) or exc)

        run_async(work, ok, err)

    def _add(self):
        payload = {
            "name": (self.name_field.text or "").strip(),
            "mobile": (self.mobile_field.text or "").strip(),
            "location": (self.location_field.text or "").strip(),
            "gross_salary": (self.salary_field.text or "").strip() or "0",
        }

        def work():
            return payroll_api.create_employee(self.app.api, payload)

        def ok(_data):
            toast("Added")
            self.name_field.text = ""
            self.mobile_field.text = ""
            self.location_field.text = ""
            self.salary_field.text = ""
            self._reload()

        def fail(exc):
            toast(str(getattr(exc, "message", exc) or exc))

        run_async(work, ok, fail)
