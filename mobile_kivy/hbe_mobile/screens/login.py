"""Login screen — clean hospitality card matching latest reference."""

from __future__ import annotations

import io
from pathlib import Path

from kivy.core.image import Image as CoreImage
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.metrics import dp
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.image import Image
from kivy.uix.scrollview import ScrollView
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton, MDTextButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.textfield import MDTextField
from kivymd.toast import toast

from hbe_mobile import theme
from hbe_mobile.api import auth as auth_api
from hbe_mobile.utils.async_jobs import run_async

_ASSETS = Path(__file__).resolve().parents[2] / "assets"
_BELLA_LIGHT_MARK = _ASSETS / "bella_light_mark.png"
_LOGIN_BG = _ASSETS / "login_bg.jpg"


class _GoldOrnament(Widget):
    """Thin gold rule with center diamond (reference divider)."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.size_hint_y = None
        self.height = dp(18)
        with self.canvas:
            Color(0.77, 0.64, 0.42, 1)
            self._left = Rectangle(size=(dp(48), dp(1)))
            self._right = Rectangle(size=(dp(48), dp(1)))
            self._diamond = RoundedRectangle(size=(dp(7), dp(7)), radius=[dp(1)])
        self.bind(pos=self._layout, size=self._layout)

    def _layout(self, *_args):
        cy = self.y + self.height / 2
        cx = self.x + self.width / 2
        self._left.pos = (cx - dp(64), cy)
        self._right.pos = (cx + dp(16), cy)
        self._diamond.pos = (cx - dp(3.5), cy - dp(3))


class LoginScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "login"
        self._captcha_required = False
        self._password_hidden = True

        root = FloatLayout()

        if _LOGIN_BG.is_file():
            root.add_widget(
                Image(
                    source=str(_LOGIN_BG),
                    allow_stretch=True,
                    keep_ratio=False,
                    size_hint=(1, 1),
                    pos_hint={"x": 0, "y": 0},
                )
            )
        root.add_widget(
            MDBoxLayout(
                md_bg_color=(0.92, 0.95, 0.98, 0.72),
                size_hint=(1, 1),
                pos_hint={"x": 0, "y": 0},
            )
        )
        root.add_widget(
            MDBoxLayout(
                md_bg_color=(0.78, 0.88, 0.96, 0.45),
                size_hint=(1.4, None),
                height=dp(100),
                pos_hint={"center_x": 0.5, "top": 1.06},
                radius=[dp(80)],
            )
        )
        root.add_widget(
            MDBoxLayout(
                md_bg_color=(0.82, 0.90, 0.97, 0.5),
                size_hint=(1.4, None),
                height=dp(110),
                pos_hint={"center_x": 0.5, "y": -0.06},
                radius=[dp(80)],
            )
        )

        scroll = ScrollView(size_hint=(1, 1), do_scroll_x=False, bar_width=0)
        scroll_body = MDBoxLayout(
            orientation="vertical",
            size_hint_y=None,
            padding=[dp(18), dp(36), dp(18), dp(36)],
            spacing=dp(8),
        )
        scroll_body.bind(minimum_height=scroll_body.setter("height"))

        self._panel = MDCard(
            orientation="vertical",
            padding=[dp(22), dp(26), dp(22), dp(20)],
            spacing=dp(10),
            size_hint=(1, None),
            height=dp(560),
            radius=[dp(24)],
            md_bg_color=theme.SURFACE,
            elevation=2,
        )

        mark = Image(
            source=str(_BELLA_LIGHT_MARK) if _BELLA_LIGHT_MARK.is_file() else "",
            size_hint=(None, None),
            size=(dp(64), dp(64)),
            pos_hint={"center_x": 0.5},
            allow_stretch=True,
            keep_ratio=True,
        )
        self._panel.add_widget(mark)
        self._panel.add_widget(
            MDLabel(
                text="Hotel Bell Elite",
                font_style="H5",
                bold=True,
                halign="center",
                theme_text_color="Custom",
                text_color=theme.LOGIN_NAVY,
                size_hint_y=None,
                height=dp(36),
            )
        )
        self._panel.add_widget(_GoldOrnament())
        self._panel.add_widget(
            MDLabel(
                text="HOSPITALITY  ·  COMFORT  ·  EXCELLENCE",
                font_style="Caption",
                halign="center",
                theme_text_color="Custom",
                text_color=theme.LOGIN_TAGLINE_GOLD,
                size_hint_y=None,
                height=dp(20),
                bold=True,
            )
        )
        self._panel.add_widget(
            MDLabel(
                text="Welcome Back",
                font_style="H6",
                bold=True,
                halign="center",
                theme_text_color="Custom",
                text_color=theme.LOGIN_NAVY,
                size_hint_y=None,
                height=dp(30),
            )
        )
        self._panel.add_widget(
            MDLabel(
                text="Sign in to access your account",
                font_style="Body2",
                halign="center",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                size_hint_y=None,
                height=dp(22),
            )
        )

        self.user_field = MDTextField(
            hint_text="Username",
            helper_text="Enter your username",
            helper_text_mode="on_focus",
            mode="rectangle",
            icon_left="account-outline",
            size_hint_y=None,
            height=dp(56),
        )
        pass_row = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(56),
            spacing=dp(4),
        )
        self.pass_field = MDTextField(
            hint_text="Password",
            helper_text="Enter your password",
            helper_text_mode="on_focus",
            mode="rectangle",
            icon_left="lock-outline",
            password=True,
            size_hint_x=0.86,
        )
        self._eye_btn = MDIconButton(
            icon="eye-outline",
            theme_icon_color="Custom",
            icon_color=theme.TEXT_MUTED,
            on_release=lambda *_: self._toggle_password(),
        )
        pass_row.add_widget(self.pass_field)
        pass_row.add_widget(self._eye_btn)

        self.captcha_field = MDTextField(
            hint_text="CAPTCHA",
            mode="rectangle",
            disabled=True,
            size_hint_y=None,
            height=0,
            opacity=0,
        )
        self.captcha_image = Image(size_hint_y=None, height=0, opacity=0)
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

        self._panel.add_widget(self.user_field)
        self._panel.add_widget(pass_row)
        self._panel.add_widget(self.captcha_image)
        self._panel.add_widget(self.captcha_field)
        self._panel.add_widget(self.refresh_captcha_btn)
        self._panel.add_widget(self.error_label)

        self.sign_in_btn = MDRaisedButton(
            text="Sign In  →",
            md_bg_color="#3B82F6",
            size_hint_x=1,
            pos_hint={"center_x": 0.5},
            on_release=lambda *_: self._do_login(),
        )
        self._panel.add_widget(self.sign_in_btn)

        trust = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(32),
            spacing=dp(4),
            padding=[dp(24), 0, dp(24), 0],
        )
        trust.add_widget(
            MDBoxLayout(md_bg_color=(0.9, 0.93, 0.96, 1), size_hint_y=None, height=dp(1))
        )
        trust.add_widget(
            MDIconButton(
                icon="shield-check-outline",
                theme_icon_color="Custom",
                icon_color="#8AA4BC",
                icon_size="16sp",
                disabled=True,
            )
        )
        trust.add_widget(
            MDLabel(
                text="Secure & Trusted",
                font_style="Caption",
                theme_text_color="Custom",
                text_color="#8AA4BC",
                size_hint_x=None,
                width=dp(110),
            )
        )
        trust.add_widget(
            MDBoxLayout(md_bg_color=(0.9, 0.93, 0.96, 1), size_hint_y=None, height=dp(1))
        )
        self._panel.add_widget(trust)

        scroll_body.add_widget(self._panel)
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
            self.captcha_field.height = dp(56)
            self.refresh_captcha_btn.opacity = 1
            self.refresh_captcha_btn.disabled = False
            self.refresh_captcha_btn.height = dp(36)
            self._panel.height = dp(700)
        else:
            self.captcha_image.opacity = 0
            self.captcha_image.height = 0
            self.captcha_field.disabled = True
            self.captcha_field.text = ""
            self.captcha_field.opacity = 0
            self.captcha_field.height = 0
            self.refresh_captcha_btn.opacity = 0
            self.refresh_captcha_btn.disabled = True
            self.refresh_captcha_btn.height = 0
            self._panel.height = dp(560)

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
                self.error_label.text = "Password change required — use the web app first."
                toast("Complete password change on web, then sign in again.")
                self.app.api.logout()
                return
            self.error_label.text = ""
            self._set_captcha_visible(False)
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
