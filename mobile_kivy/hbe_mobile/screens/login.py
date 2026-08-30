"""Login screen — light airy hospitality layout (no photo, no card chrome)."""

from __future__ import annotations

import io
from pathlib import Path

from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Line, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDTextButton
from kivymd.uix.label import MDIcon, MDLabel
from kivymd.uix.screen import MDScreen

from hbe_mobile import theme
from hbe_mobile.api import auth as auth_api
from hbe_mobile.utils.async_jobs import run_async

_ASSETS = Path(__file__).resolve().parents[2] / "assets"
_BELLA_LIGHT_MARK = _ASSETS / "bella_light_mark.png"

_FIELD_BORDER = (0.886, 0.910, 0.941, 1)  # #E2E8F0
_ICON_MUTED = (0.580, 0.639, 0.722, 1)  # #94A3B8
_PLACEHOLDER = (0.580, 0.639, 0.722, 1)


class _GoldRule(Widget):
    """Short 32×2 gold rule under the mark."""

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
        self._bar.pos = (
            self.x + (self.width - dp(32)) / 2,
            self.y + (self.height - dp(2)) / 2,
        )


class _FieldBox(MDBoxLayout):
    """White 52dp field, 20dp radius, 1px #E2E8F0 — no floating Material label."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(52)
        self.padding = [dp(16), 0, dp(4), 0]
        self.spacing = dp(8)
        self.radius = [dp(20)]
        self.md_bg_color = theme.SURFACE
        with self.canvas.after:
            Color(*_FIELD_BORDER)
            self._stroke = Line(width=1.1)
        self.bind(pos=self._sync_stroke, size=self._sync_stroke)

    def _sync_stroke(self, *_args):
        r = dp(20)
        self._stroke.rounded_rectangle = (
            self.x + 0.5,
            self.y + 0.5,
            max(0, self.width - 1),
            max(0, self.height - 1),
            r,
        )


class _PlainInput(TextInput):
    """Transparent TextInput so the rounded field chrome shows through."""

    def __init__(self, **kwargs):
        kwargs.setdefault("multiline", False)
        kwargs.setdefault("write_tab", False)
        kwargs.setdefault("font_size", "15sp")
        kwargs.setdefault("foreground_color", (0.102, 0.125, 0.173, 1))  # #1A202C
        kwargs.setdefault("hint_text_color", _PLACEHOLDER)
        kwargs.setdefault("cursor_color", (0.094, 0.467, 0.949, 1))  # #1877F2
        kwargs.setdefault("padding", [0, dp(16), 0, dp(16)])
        kwargs.setdefault("background_color", (1, 1, 1, 0))
        super().__init__(**kwargs)
        self.background_normal = ""
        self.background_active = ""
        self.background_disabled_normal = ""
        self.background_disabled_active = ""
        self.background_color = (1, 1, 1, 0)


class _SignInPill(ButtonBehavior, MDBoxLayout):
    """Full-width 52dp pill — MDFillRoundFlatButton equivalent that actually stretches."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "horizontal"
        self.size_hint_x = 1
        self.size_hint_y = None
        self.height = dp(52)
        self.radius = [dp(26)]
        self.md_bg_color = theme.ACCENT
        self.padding = [dp(16), 0]
        self._label = MDLabel(
            text="Sign In",
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=(1, 1, 1, 1),
            bold=True,
            font_size="16sp",
        )
        self.add_widget(self._label)
        self.bind(disabled=self._on_disabled)

    def _on_disabled(self, _inst, value):
        self.opacity = 0.55 if value else 1.0


class LoginScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "login"
        self._captcha_required = False
        self._password_hidden = True
        self.md_bg_color = theme.BG

        root = MDBoxLayout(
            orientation="vertical",
            md_bg_color=theme.BG,
            size_hint=(1, 1),
            padding=[0, dp(12), 0, dp(12)],
        )

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False, bar_width=0)
        scroll_body = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            md_bg_color=theme.BG,
        )
        scroll_body.bind(minimum_height=scroll_body.setter("height"))

        def _fit(*_a):
            min_h = scroll_body.minimum_height
            scroll_body.height = max(min_h, scroll.height)

        scroll.bind(height=_fit)
        scroll_body.bind(minimum_height=_fit)

        top_air = Widget(size_hint_y=None)
        bottom_air = Widget(size_hint_y=None)

        def _air(*_a):
            extra = max(0, scroll.height - 560)
            top_air.height = dp(56) + extra * 0.42
            bottom_air.height = dp(32) + extra * 0.58
            _fit()

        scroll.bind(height=_air)

        col = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=[dp(32), 0, dp(32), 0],
            spacing=0,
        )
        col.bind(minimum_height=col.setter("height"))
        self._panel = col

        mark = Image(
            source=str(_BELLA_LIGHT_MARK) if _BELLA_LIGHT_MARK.is_file() else "",
            size_hint=(None, None),
            size=(dp(56), dp(56)),
            pos_hint={"center_x": 0.5},
            allow_stretch=True,
            keep_ratio=True,
        )
        col.add_widget(mark)
        col.add_widget(_GoldRule())

        title = MDLabel(
            text="Hotel Bell Elite",
            halign="center",
            theme_text_color="Custom",
            text_color=theme.TEXT,
            bold=True,
            size_hint_y=None,
            height=dp(40),
        )
        title.font_size = "28sp"
        col.add_widget(title)

        subtitle = MDLabel(
            text="Sign in to continue",
            halign="center",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            size_hint_y=None,
            height=dp(28),
        )
        subtitle.font_size = "15sp"
        col.add_widget(subtitle)
        col.add_widget(Widget(size_hint_y=None, height=dp(36)))

        col.add_widget(
            MDLabel(
                text="Username",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                size_hint_y=None,
                height=dp(20),
                font_size="12sp",
            )
        )
        col.add_widget(Widget(size_hint_y=None, height=dp(8)))
        user_box = _FieldBox()
        user_box.add_widget(
            MDIcon(
                icon="account-outline",
                theme_text_color="Custom",
                text_color=_ICON_MUTED,
                size_hint=(None, None),
                size=(dp(22), dp(22)),
                pos_hint={"center_y": 0.5},
                font_size="20sp",
            )
        )
        self.user_field = _PlainInput(hint_text="Username")
        user_box.add_widget(self.user_field)
        col.add_widget(user_box)
        col.add_widget(Widget(size_hint_y=None, height=dp(16)))

        col.add_widget(
            MDLabel(
                text="Password",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                size_hint_y=None,
                height=dp(20),
                font_size="12sp",
            )
        )
        col.add_widget(Widget(size_hint_y=None, height=dp(8)))
        pass_box = _FieldBox()
        pass_box.add_widget(
            MDIcon(
                icon="lock-outline",
                theme_text_color="Custom",
                text_color=_ICON_MUTED,
                size_hint=(None, None),
                size=(dp(22), dp(22)),
                pos_hint={"center_y": 0.5},
                font_size="20sp",
            )
        )
        self.pass_field = _PlainInput(hint_text="Password", password=True)
        pass_box.add_widget(self.pass_field)
        self._eye_btn = MDIconButton(
            icon="eye-outline",
            theme_icon_color="Custom",
            icon_color=_ICON_MUTED,
            on_release=lambda *_: self._toggle_password(),
            pos_hint={"center_y": 0.5},
            size_hint=(None, None),
            size=(dp(40), dp(40)),
        )
        pass_box.add_widget(self._eye_btn)
        col.add_widget(pass_box)

        self.captcha_image = Image(size_hint_y=None, height=0, opacity=0)
        captcha_box = _FieldBox()
        captcha_box.height = 0
        captcha_box.opacity = 0
        captcha_box.disabled = True
        self._captcha_box = captcha_box
        self.captcha_field = _PlainInput(hint_text="CAPTCHA", disabled=True)
        captcha_box.add_widget(self.captcha_field)
        self.refresh_captcha_btn = MDTextButton(
            text="Refresh CAPTCHA",
            pos_hint={"center_x": 0.5},
            on_release=lambda *_: self._load_captcha(),
            size_hint_y=None,
            height=0,
            opacity=0,
            disabled=True,
        )

        self.error_label = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=(0.8, 0.2, 0.2, 1),
            size_hint_y=None,
            height=dp(22),
            halign="center",
        )

        col.add_widget(Widget(size_hint_y=None, height=dp(8)))
        col.add_widget(self.captcha_image)
        col.add_widget(captcha_box)
        col.add_widget(self.refresh_captcha_btn)
        col.add_widget(self.error_label)
        col.add_widget(Widget(size_hint_y=None, height=dp(16)))

        # Full-width 52dp pill (MDFillRoundFlatButton in 1.2 kv-locks width to text).
        self.sign_in_btn = _SignInPill(on_release=lambda *_: self._do_login())
        col.add_widget(self.sign_in_btn)

        staff = MDLabel(
            text="Staff",
            halign="center",
            theme_text_color="Custom",
            text_color=_ICON_MUTED,
            size_hint_y=None,
            height=dp(36),
        )
        staff.font_size = "11sp"
        col.add_widget(Widget(size_hint_y=None, height=dp(20)))
        col.add_widget(staff)

        scroll_body.add_widget(top_air)
        scroll_body.add_widget(col)
        scroll_body.add_widget(bottom_air)
        scroll.add_widget(scroll_body)
        root.add_widget(scroll)
        self.add_widget(root)
        self._set_captcha_visible(False)

    def _toggle_password(self) -> None:
        self._password_hidden = not self._password_hidden
        self.pass_field.password = self._password_hidden
        self._eye_btn.icon = "eye-outline" if self._password_hidden else "eye-off-outline"

    def _set_captcha_visible(self, visible: bool) -> None:
        self._captcha_required = visible
        if visible:
            self.captcha_image.opacity = 1
            self.captcha_image.height = dp(48)
            self.captcha_field.disabled = False
            self.captcha_field.opacity = 1
            self._captcha_box.height = dp(52)
            self._captcha_box.opacity = 1
            self._captcha_box.disabled = False
            self.refresh_captcha_btn.opacity = 1
            self.refresh_captcha_btn.disabled = False
            self.refresh_captcha_btn.height = dp(36)
        else:
            self.captcha_image.opacity = 0
            self.captcha_image.height = 0
            self.captcha_field.disabled = True
            self.captcha_field.text = ""
            self.captcha_field.opacity = 0
            self._captcha_box.height = 0
            self._captcha_box.opacity = 0
            self._captcha_box.disabled = True
            self.refresh_captcha_btn.opacity = 0
            self.refresh_captcha_btn.disabled = True
            self.refresh_captcha_btn.height = 0

    def _do_login(self) -> None:
        username = (self.user_field.text or "").strip()
        password = self.pass_field.text or ""
        captcha = (self.captcha_field.text or "").strip() if self._captcha_required else ""
        if not username or not password:
            self.error_label.text = "Enter username and password."
            return
        self.sign_in_btn.disabled = True
        self.error_label.text = "Signing in…"

        def work():
            return auth_api.login(self.app.api, username, password, captcha=captcha)

        def ok(session):
            self.sign_in_btn.disabled = False
            if not session.authenticated:
                self.error_label.text = session.error or "Sign-in failed"
                if session.captcha_required:
                    self._set_captcha_visible(True)
                    self._load_captcha()
                else:
                    self._set_captcha_visible(False)
                return
            if session.must_change_password:
                self.app.api.logout()
                self.clear_fields()
                self.error_label.text = "Password change required — use the web app first."
                toast("Complete password change on web, then sign in again.")
                return
            self.clear_fields()
            self.app.on_login_success(session)

        def err(exc):
            self.sign_in_btn.disabled = False
            self.error_label.text = str(exc)

        run_async(work, ok, err)

    def _load_captcha(self) -> None:
        if not self._captcha_required:
            return

        def work():
            return self.app.api.fetch_captcha_png()

        def ok(png: bytes):
            data = io.BytesIO(png)
            core = CoreImage(data, ext="png")
            self.captcha_image.texture = core.texture
            self.captcha_image.opacity = 1
            self.captcha_field.disabled = False

        def err(exc):
            toast(f"CAPTCHA unavailable: {exc}")

        run_async(work, ok, err)

    def clear_fields(self) -> None:
        """Wipe username, password, and captcha. Password is never persisted."""
        self.user_field.text = ""
        self.pass_field.text = ""
        self.captcha_field.text = ""
        self._set_captcha_visible(False)
        self.error_label.text = ""
