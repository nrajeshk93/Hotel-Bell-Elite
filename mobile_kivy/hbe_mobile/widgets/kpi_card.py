"""KPI / module card widgets."""

from __future__ import annotations

from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel

from hbe_mobile import theme


def _format_change(change_pct) -> tuple[str, str]:
    """Return (text, color) for a signed change percent using SUCCESS/DANGER."""
    if change_pct is None or change_pct == "":
        return "", theme.TEXT_MUTED
    try:
        n = float(change_pct)
    except (TypeError, ValueError):
        return str(change_pct), theme.TEXT_MUTED
    abs_n = abs(n)
    body = f"{int(abs_n)}%" if abs_n == int(abs_n) else f"{abs_n:.1f}%"
    if n > 0:
        return f"+{body}", theme.SUCCESS
    if n < 0:
        return f"\u2212{body}", theme.DANGER
    return f"{body}", theme.TEXT_MUTED


def _parse_hex(color: str) -> tuple[float, float, float, float]:
    value = (color or "").strip().lstrip("#")
    if len(value) == 6:
        r = int(value[0:2], 16) / 255.0
        g = int(value[2:4], 16) / 255.0
        b = int(value[4:6], 16) / 255.0
        return (r, g, b, 1.0)
    return (0.1, 0.15, 0.27, 1.0)


class KpiCard(MDCard):
    title = StringProperty("")
    value = StringProperty("")
    subtitle = StringProperty("")

    def __init__(self, **kwargs):
        change_pct = kwargs.pop("change_pct", None)
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.padding = dp(14)
        self.spacing = dp(4)
        self.size_hint_y = None
        self.radius = [dp(12)]
        self.md_bg_color = theme.SURFACE
        self.elevation = 1
        self._title = MDLabel(
            text=self.title,
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            font_style="Caption",
            size_hint_y=None,
            height=dp(20),
            shorten=True,
        )
        self._value = MDLabel(
            text=self.value,
            theme_text_color="Custom",
            text_color=theme.TEXT,
            font_style="H6",
            bold=True,
            size_hint_y=None,
            height=dp(28),
            shorten=True,
        )
        self._meta = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            font_style="Caption",
            size_hint_y=None,
            height=dp(18),
            shorten=True,
        )
        self.add_widget(self._title)
        self.add_widget(self._value)
        self.add_widget(self._meta)
        self.bind(title=lambda *_: setattr(self._title, "text", self.title))
        self.bind(value=lambda *_: setattr(self._value, "text", self.value))
        self.bind(subtitle=lambda *_: self._refresh_meta())
        self._change_pct = change_pct
        self._refresh_meta()
        self._sync_height()

    def _sync_height(self) -> None:
        has_meta = bool(self._meta.text)
        self.height = dp(112) if has_meta else dp(96)
        self._meta.opacity = 1 if has_meta else 0
        self._meta.height = dp(18) if has_meta else 0

    def _refresh_meta(self) -> None:
        change_text, change_color = _format_change(self._change_pct)
        parts = [p for p in (change_text, (self.subtitle or "").strip()) if p]
        self._meta.text = " ".join(parts)
        self._meta.text_color = change_color if change_text else theme.TEXT_MUTED
        self._sync_height()

    def set_change(self, change_pct) -> None:
        self._change_pct = change_pct
        self._refresh_meta()


class ExecKpiCard(KpiCard):
    """Executive KPI: title, rupee value, optional change % (SUCCESS/DANGER)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.height = dp(112)
        self._meta.opacity = 1
        self._meta.height = dp(18)


class ModuleCard(ButtonBehavior, MDBoxLayout):
    title = StringProperty("")
    subtitle = StringProperty("")

    def __init__(self, **kwargs):
        accent_color = kwargs.pop("accent_color", theme.LOGIN_NAVY)
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.padding = (0, dp(14), dp(12), dp(14))
        self.spacing = dp(10)
        self.size_hint_y = None
        self.height = dp(84)
        self.md_bg_color = theme.SURFACE

        with self.canvas.before:
            Color(1, 1, 1, 1)
            self._bg = RoundedRectangle(radius=[dp(14)], pos=self.pos, size=self.size)
            Color(*_parse_hex(accent_color))
            self._accent = RoundedRectangle(
                radius=[dp(14), 0, 0, dp(14)],
                pos=self.pos,
                size=(dp(5), self.height),
            )

        def _sync_chrome(*_args):
            self._bg.pos = self.pos
            self._bg.size = self.size
            self._accent.pos = self.pos
            self._accent.size = (dp(5), self.height)

        self.bind(pos=_sync_chrome, size=_sync_chrome)

        copy = MDBoxLayout(orientation="vertical", spacing=dp(2), padding=(dp(14), 0, 0, 0))
        self._title = MDLabel(
            text=self.title,
            theme_text_color="Custom",
            text_color=theme.LOGIN_NAVY,
            font_style="H6",
            bold=True,
            size_hint_y=None,
            height=dp(28),
        )
        self._sub = MDLabel(
            text=self.subtitle,
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            font_style="Caption",
            size_hint_y=None,
            height=dp(20),
        )
        copy.add_widget(self._title)
        copy.add_widget(self._sub)
        self.add_widget(copy)
        self.add_widget(
            MDLabel(
                text="›",
                theme_text_color="Custom",
                text_color="#94A3B8",
                font_style="H5",
                bold=True,
                size_hint_x=None,
                width=dp(22),
                halign="center",
                valign="middle",
            )
        )
        self.bind(title=lambda *_: setattr(self._title, "text", self.title))
        self.bind(subtitle=lambda *_: setattr(self._sub, "text", self.subtitle))
