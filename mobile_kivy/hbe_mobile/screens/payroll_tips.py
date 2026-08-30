"""Tips analytics summary + add tip."""

from __future__ import annotations

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from hbe_mobile import theme
from hbe_mobile.api import payroll as payroll_api
from hbe_mobile.utils.async_jobs import run_async

_ACCENT = theme.ACCENT
_SOFT = getattr(theme, "ACCENT_SOFT", "#E8F1FE")
_WHITE = "#FFFFFF"
_CHIP_BORDER = "#E2E8F0"
_CARD_LINE = "#EEF1F4"
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fmt(iso: str) -> str:
    parts = (iso or "")[:10].split("-")
    if len(parts) != 3:
        return iso or "Select date…"
    try:
        y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{d:02d} {_MONTHS[m - 1]} {y}"
    except Exception:
        return iso or "Select date…"


def _style_md_date_picker(picker):
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
        picker.firstweekday = 0
    except Exception:
        pass
    return picker


class _GoldRule(Widget):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(16)
        with self.canvas:
            Color(0.769, 0.643, 0.416, 1)  # #C4A46A
            self._bar = Rectangle(size=(dp(32), dp(2)))
        self.bind(pos=self._layout, size=self._layout)

    def _layout(self, *_args):
        self._bar.size = (dp(32), dp(2))
        self._bar.pos = (self.x, self.y + (self.height - dp(2)) / 2)


class _Chip(ButtonBehavior, MDCard):
    def __init__(self, caption: str, on_press, **kwargs):
        super().__init__(**kwargs)
        self._on_press = on_press
        self.orientation = "horizontal"
        self.size_hint = (None, None)
        self.height = dp(32)
        self.padding = [dp(14), 0, dp(14), 0]
        self.radius = [dp(20)]
        self.elevation = 0
        self.line_width = 1
        self._caption = MDLabel(
            text=caption, halign="center", valign="middle",
            theme_text_color="Custom", font_style="Caption", bold=True,
        )
        self.add_widget(self._caption)
        self.set_caption(caption)
        self.set_selected(False)

    def set_caption(self, caption: str) -> None:
        self._caption.text = caption
        self.width = max(dp(72), dp(24) + len(caption) * dp(7.2))

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.md_bg_color = _ACCENT
            self.line_color = _ACCENT
            self._caption.text_color = _WHITE
        else:
            self.md_bg_color = theme.SURFACE
            self.line_color = _CHIP_BORDER
            self._caption.text_color = theme.TEXT

    def on_release(self):
        if self._on_press:
            self._on_press()


class PayrollTipsScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "payroll_tips"
        self.md_bg_color = theme.BG
        self._outlet = "Hotel"
        self._filter_loc = "All"
        self._date_from = ""
        self._date_to = ""
        self._entry_iso = payroll_api.today_iso()
        self._loc_chips: dict[str, _Chip] = {}

        root = MDBoxLayout(orientation="vertical", padding=[dp(20), dp(12), dp(20), dp(16)], spacing=dp(8))
        root.add_widget(MDLabel(
            text="Tips", font_style="H5", bold=True,
            theme_text_color="Custom", text_color=theme.TEXT,
            size_hint_y=None, height=dp(36),
        ))
        root.add_widget(_GoldRule())
        self.status = MDLabel(
            text="Loading tips…", theme_text_color="Custom", text_color=theme.TEXT_MUTED,
            font_style="Caption", size_hint_y=None, height=dp(18),
        )
        root.add_widget(self.status)

        self.date_chip = _Chip("Select date…", lambda: self._open_range_picker())
        self.date_chip.width = dp(168)
        root.add_widget(self.date_chip)

        loc_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(8))
        for loc in ("All", "Hotel", "Restaurant", "Bar"):
            chip = _Chip(loc, lambda *_a, v=loc: self._set_filter(v))
            self._loc_chips[loc] = chip
            loc_row.add_widget(chip)
        self._loc_chips["All"].set_selected(True)
        root.add_widget(loc_row)

        scroll = MDScrollView()
        self.list_box = MDBoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None, padding=(0, 4, 0, 16))
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)

        form = MDCard(
            orientation="vertical", padding=dp(16), spacing=dp(8),
            size_hint_y=None, height=dp(268),
            md_bg_color=theme.SURFACE, radius=[dp(20)], elevation=0,
            line_color=_CARD_LINE, line_width=1,
        )
        form.add_widget(MDLabel(text="Add tip", bold=True, theme_text_color="Custom", text_color=theme.TEXT, size_hint_y=None, height=dp(22)))
        out_row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(6))
        self._outlet_chips = {}
        for loc in ("Hotel", "Restaurant", "Bar"):
            chip = _Chip(loc, lambda *_a, v=loc: self._set_outlet(v))
            self._outlet_chips[loc] = chip
            out_row.add_widget(chip)
        self._outlet_chips["Hotel"].set_selected(True)
        self.emp_field = MDTextField(hint_text="Employee ID", size_hint_y=None, height=dp(44))
        self.amount_field = MDTextField(hint_text="Amount", size_hint_y=None, height=dp(44))
        self.date_field = MDTextField(hint_text="Date YYYY-MM-DD", text=self._entry_iso, size_hint_y=None, height=dp(44))
        self.date_btn = _Chip(_fmt(self._entry_iso), lambda: self._open_entry_picker())
        self.date_btn.width = dp(160)
        form.add_widget(out_row)
        form.add_widget(self.emp_field)
        form.add_widget(self.amount_field)
        form.add_widget(self.date_btn)
        form.add_widget(MDRaisedButton(text="Send", md_bg_color=theme.ACCENT, size_hint_y=None, height=dp(32), on_release=lambda *_: self._save()))
        root.add_widget(form)
        self.add_widget(root)

    def on_pre_enter(self, *args):
        self._reload()

    def _set_outlet(self, value):
        self._outlet = value
        for loc, chip in self._outlet_chips.items():
            chip.set_selected(loc == value)

    def _set_filter(self, value):
        self._filter_loc = value
        for loc, chip in self._loc_chips.items():
            chip.set_selected(loc == value)
        self._reload()

    def _open_range_picker(self):
        try:
            from kivymd.uix.pickers import MDDatePicker
        except Exception:
            toast("Date picker unavailable")
            return
        try:
            picker = MDDatePicker(mode="range")
        except Exception:
            picker = MDDatePicker()
        _style_md_date_picker(picker)
        picker.bind(on_save=self._on_range_save)
        picker.open()

    def _on_range_save(self, _picker, value, date_range):
        try:
            dates = list(date_range or [])
        except Exception:
            dates = []
        if len(dates) >= 2:
            self._date_from = dates[0].isoformat()[:10]
            self._date_to = dates[-1].isoformat()[:10]
        elif value is not None:
            iso = value.isoformat()[:10]
            self._date_from = iso
            self._date_to = iso
        if self._date_from and self._date_to:
            self.date_chip.set_caption(f"{_fmt(self._date_from)[:7]} – {_fmt(self._date_to)[:7]}")
            self.date_chip.width = dp(188)
        self._reload()

    def _open_entry_picker(self):
        try:
            from kivymd.uix.pickers import MDDatePicker
        except Exception:
            toast("Date picker unavailable")
            return
        parts = (self._entry_iso or payroll_api.today_iso())[:10].split("-")
        try:
            y, m, d = int(parts[0]), int(parts[1]), int(parts[2])
        except Exception:
            from datetime import date as _date
            today = _date.today()
            y, m, d = today.year, today.month, today.day
        picker = _style_md_date_picker(MDDatePicker(year=y, month=m, day=d))
        picker.bind(on_save=self._on_entry_save)
        picker.open()

    def _on_entry_save(self, _picker, value, _date_range):
        try:
            self._entry_iso = value.isoformat()[:10]
        except Exception:
            self._entry_iso = str(value)[:10]
        self.date_field.text = self._entry_iso
        self.date_btn.set_caption(_fmt(self._entry_iso))

    def _kpi(self, label: str, value) -> MDCard:
        card = MDCard(
            orientation="vertical", padding=[dp(16), dp(14)], size_hint_y=None, height=dp(72),
            md_bg_color=theme.SURFACE, radius=[dp(20)], elevation=0,
            line_color=_CARD_LINE, line_width=1,
        )
        card.add_widget(MDLabel(text=label, theme_text_color="Custom", text_color=_ACCENT, font_style="Caption", size_hint_y=None, height=dp(16)))
        card.add_widget(MDLabel(text=f"₹{value or 0}", bold=True, theme_text_color="Custom", text_color=theme.TEXT, size_hint_y=None, height=dp(24)))
        return card

    def _row_card(self, title: str, meta: str, amount) -> MDCard:
        card = MDCard(
            orientation="vertical", padding=dp(14), size_hint_y=None, height=dp(72),
            md_bg_color=theme.SURFACE, radius=[dp(20)], elevation=0,
            line_color=_CARD_LINE, line_width=1,
        )
        top = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
        top.add_widget(MDLabel(text=title, theme_text_color="Custom", text_color=theme.TEXT_MUTED, font_style="Caption"))
        top.add_widget(MDLabel(text=f"₹{amount or 0}", bold=True, halign="right", theme_text_color="Custom", text_color=theme.TEXT))
        card.add_widget(top)
        card.add_widget(MDLabel(text=meta, theme_text_color="Custom", text_color=theme.TEXT_MUTED, font_style="Caption", size_hint_y=None, height=dp(18)))
        return card

    def _reload(self):
        params = {}
        if self._date_from:
            params["date_from"] = self._date_from
        if self._date_to:
            params["date_to"] = self._date_to
        if self._filter_loc:
            params["location"] = self._filter_loc

        def work():
            return payroll_api.fetch_tips(self.app.api, **params)

        def ok(data):
            self.status.text = f"Tips ₹{data.get('grand_total') or 0}"
            self.list_box.clear_widgets()
            grid = MDBoxLayout(orientation="vertical", spacing=dp(10), size_hint_y=None)
            grid.bind(minimum_height=grid.setter("height"))
            for label, key in (("Total", "grand_total"), ("Hotel", "hotel_total"), ("Bar", "bar_total"), ("Restaurant", "restaurant_total")):
                grid.add_widget(self._kpi(label, data.get(key)))
            self.list_box.add_widget(grid)
            for row in data.get("top_employees") or []:
                self.list_box.add_widget(self._row_card(str(row.get("employee_name") or ""), str(row.get("employee_code") or ""), row.get("total")))
            if not data.get("top_employees"):
                self.list_box.add_widget(MDLabel(text="No tips in this range.", size_hint_y=None, height=dp(28)))
            for row in data.get("recent") or []:
                meta = " · ".join(part for part in [str(row.get("date") or ""), str(row.get("location") or "")] if part)
                self.list_box.add_widget(self._row_card(str(row.get("employee_name") or ""), meta, row.get("amount")))

        def err(exc):
            self.status.text = str(getattr(exc, "message", exc) or exc)

        run_async(work, ok, err)

    def _save(self):
        payload = {
            "employee_id": (self.emp_field.text or "").strip(),
            "amount": (self.amount_field.text or "").strip(),
            "date": (self.date_field.text or "").strip() or self._entry_iso or payroll_api.today_iso(),
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
