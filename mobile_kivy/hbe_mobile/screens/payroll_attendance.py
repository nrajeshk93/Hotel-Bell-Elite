"""Attendance date view — mark present / absent / half day / clear."""

from __future__ import annotations

from kivy.metrics import dp
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRoundFlatButton
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

_BLUE = (0.094, 0.467, 0.949, 1)  # #1877F2
_CHIP_BG = {
    "present": (0.859, 0.918, 0.996, 1),
    "absent": (0.996, 0.886, 0.886, 1),
    "half_day": (0.996, 0.953, 0.780, 1),
    "unmarked": (0.933, 0.949, 0.969, 1),
}
_CHIP_FG = {
    "present": (0.114, 0.306, 0.847, 1),
    "absent": (0.725, 0.110, 0.110, 1),
    "half_day": (0.706, 0.325, 0.035, 1),
    "unmarked": (0.392, 0.455, 0.545, 1),
}
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


class PayrollAttendanceScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "payroll_attendance"
        self.md_bg_color = (0.957, 0.969, 0.984, 1)  # #F4F7FB
        self._busy = False
        self._reload_ev = None
        self._date_iso = payroll_api.today_iso()

        root = MDBoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))

        date_col = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(72), spacing=dp(4))
        date_col.add_widget(MDLabel(
            text="DATE",
            font_style="Caption",
            theme_text_color="Custom",
            text_color=(0.58, 0.64, 0.72, 1),
            size_hint_y=None,
            height=dp(16),
            bold=True,
        ))
        self.date_btn = MDRoundFlatButton(
            text=_format_display_date(self._date_iso),
            theme_text_color="Custom",
            text_color=theme.TEXT,
            line_color=(0.89, 0.91, 0.94, 1),
            md_bg_color=(1, 1, 1, 1),
            size_hint_x=1,
            size_hint_y=None,
            height=dp(48),
        )
        self.date_btn.bind(on_release=lambda *_: self._open_date_picker())
        date_col.add_widget(self.date_btn)
        root.add_widget(date_col)

        self.search = MDTextField(
            hint_text="Search employee…", size_hint_y=None, height=dp(48)
        )
        self.search.bind(text=lambda *_: self._queue_reload())
        root.add_widget(self.search)

        self.status = MDLabel(
            text="Loading…",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            size_hint_y=None,
            height=dp(20),
            font_style="Caption",
        )
        root.add_widget(self.status)

        scroll = MDScrollView()
        self.list_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(12),
            size_hint_y=None,
            padding=(0, 4, 0, 16),
        )
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        if not self._date_iso:
            self._date_iso = payroll_api.today_iso()
        self.date_btn.text = _format_display_date(self._date_iso)
        self._reload()

    def _open_date_picker(self):
        try:
            from kivymd.uix.pickers import MDDatePicker
        except Exception:
            toast("Date picker unavailable")
            return
        parts = (self._date_iso or payroll_api.today_iso())[:10].split("-")
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        except Exception:
            from datetime import date as _date
            today = _date.today()
            y, m, d = today.year, today.month, today.day
        picker = _style_md_date_picker(MDDatePicker(year=y, month=m, day=d))
        picker.bind(on_save=self._on_date_save)
        picker.open()

    def _on_date_save(self, _picker, value, _date_range):
        try:
            self._date_iso = value.isoformat()
        except Exception:
            self._date_iso = str(value)[:10]
        self.date_btn.text = _format_display_date(self._date_iso)
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
        d = self._date_iso or payroll_api.today_iso()
        q = (self.search.text or "").strip()

        def work():
            return payroll_api.fetch_attendance(self.app.api, date=d, q=q)

        def ok(data):
            self._busy = False
            st = data.get("payroll_state") or {}
            label = data.get("date") or ""
            self.status.text = label + (" · Locked" if st.get("locked") else "")
            self.list_box.clear_widgets()
            for row in data.get("employees") or []:
                self.list_box.add_widget(self._build_card(row))

        def err(exc):
            self._busy = False
            self.status.text = str(getattr(exc, "message", exc) or exc)

        run_async(work, ok, err)

    def _build_card(self, row):
        mark = (row.get("date_status") or "").strip() or "unmarked"
        chip_key = mark if mark in _CHIP_BG else "unmarked"
        chip_label = "half day" if mark == "half_day" else mark.replace("_", " ")
        emp_id = int(row.get("id") or 0)
        can = bool(row.get("can_modify"))

        card = MDCard(
            orientation="vertical",
            padding=dp(14),
            size_hint_y=None,
            height=dp(120),
            md_bg_color=(1, 1, 1, 1),
            radius=[dp(18)],
            elevation=0.4,
        )
        body = MDBoxLayout(orientation="horizontal", spacing=dp(8))

        left = MDBoxLayout(orientation="vertical", size_hint_x=0.4, spacing=dp(2))
        left.add_widget(
            MDLabel(
                text=str(row.get("name") or "").upper(),
                bold=True,
                size_hint_y=None,
                height=dp(22),
                theme_text_color="Custom",
                text_color=theme.TEXT,
            )
        )
        code = row.get("emp_code") or ""
        loc = row.get("location") or "—"
        left.add_widget(
            MDLabel(
                text="%s · %s" % (code, loc),
                font_style="Caption",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                size_hint_y=None,
                height=dp(18),
            )
        )
        left.add_widget(
            MDLabel(
                text="  %s  " % chip_label,
                font_style="Caption",
                theme_text_color="Custom",
                text_color=_CHIP_FG[chip_key],
                size_hint_y=None,
                height=dp(24),
            )
        )
        body.add_widget(left)

        actions = MDBoxLayout(orientation="vertical", size_hint_x=0.6, spacing=dp(6))
        row1 = MDBoxLayout(
            orientation="horizontal", spacing=dp(4), size_hint_y=None, height=dp(36)
        )
        row2 = MDBoxLayout(
            orientation="horizontal", spacing=dp(4), size_hint_y=None, height=dp(36)
        )

        def make_btn(label, status):
            active = status != "" and mark == status
            btn = MDFlatButton(
                text=label,
                theme_text_color="Custom",
                text_color=(1, 1, 1, 1) if active else _BLUE,
                md_bg_color=_BLUE if active else (1, 1, 1, 1),
                line_color=_BLUE,
                rounded_button=True,
                size_hint_x=0.5,
            )
            btn.disabled = not can
            btn.bind(on_release=lambda *_a, s=status, i=emp_id: self._mark(i, s))
            return btn

        row1.add_widget(make_btn("Present", "present"))
        row1.add_widget(make_btn("Absent", "absent"))
        row2.add_widget(make_btn("Half day", "half_day"))
        row2.add_widget(make_btn("Clear", ""))
        actions.add_widget(row1)
        actions.add_widget(row2)
        body.add_widget(actions)
        card.add_widget(body)
        return card

    def _mark(self, emp_id, status):
        d = self._date_iso or payroll_api.today_iso()

        def work():
            return payroll_api.mark_attendance(self.app.api, emp_id, d, status)

        def ok(_data):
            toast("Saved")
            self._reload()

        def fail(exc):
            toast(str(getattr(exc, "message", exc) or exc))

        run_async(work, ok, fail)
