"""Active nav row widget — blue fill/bullet like de-nav-subitem.is-active."""

from __future__ import annotations

from kivy.metrics import dp
from kivy.properties import BooleanProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.label import MDLabel

from hbe_mobile import theme


class NavItem(ButtonBehavior, MDBoxLayout):
    label = StringProperty("")
    is_active = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(40)
        self.padding = [dp(12), dp(6), dp(12), dp(6)]
        self.spacing = dp(10)
        self.radius = [dp(6)]
        # Keep a positive line width; inactive uses transparent line_color.
        self.line_width = 1
        self._bullet = MDLabel(
            text="●",
            size_hint_x=None,
            width=dp(14),
            theme_text_color="Custom",
            text_color=theme.ACCENT,
            font_style="Caption",
        )
        self._text = MDLabel(
            text=self.label,
            theme_text_color="Custom",
            text_color=theme.NAV_INACTIVE_FG,
            font_style="Body1",
            shorten=True,
        )
        self.add_widget(self._bullet)
        self.add_widget(self._text)
        self.bind(label=self._on_label, is_active=self._on_active)
        self._on_active(self, self.is_active)

    def _on_label(self, *_args):
        self._text.text = self.label

    def _on_active(self, _instance, value: bool):
        if value:
            self.md_bg_color = theme.ACCENT_SOFT
            self.line_color = theme.ACCENT_BORDER
            self._bullet.opacity = 1
            self._text.text_color = theme.NAV_ACTIVE_FG
        else:
            self.md_bg_color = (0, 0, 0, 0)
            self.line_color = (0, 0, 0, 0)
            self._bullet.opacity = 0
            self._text.text_color = theme.NAV_INACTIVE_FG
