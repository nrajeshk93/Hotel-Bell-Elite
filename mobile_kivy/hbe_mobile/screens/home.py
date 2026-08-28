"""Home module launcher + live approvals summary."""

from __future__ import annotations

from datetime import date

from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.toast import toast

from hbe_mobile import theme
from hbe_mobile.api import approvals as approvals_api
from hbe_mobile.api import notifications as notifications_api
from hbe_mobile.utils.async_jobs import run_async
from hbe_mobile.utils.nav import can_access
from hbe_mobile.widgets.kpi_card import ModuleCard


_HOME_MODULES = [
    (None, "Dashboard", "KPIs and analytics", "dashboard", theme.LOGIN_NAVY, "main_dashboard"),
    ("Purchase & Inventory", "Indent Approval", "Approve or reject indents", "indent_approvals", theme.LOGIN_GOLD, "indent_approvals"),
    ("Restaurant", "POS", "Restaurant invoice", "pos_invoice", "#64748B", "pos"),
    (None, "KOT", "Restaurant kitchen tokens", "kot", "#64748B", "kot"),
    ("Bar", "POS", "Bar invoice", "pos_bar_invoice", "#64748B", "pos_bar"),
    (None, "KOT", "Bar kitchen tokens", "kot_bar", "#64748B", "kot_bar"),
    ("Accounts", "Approvals", "Purchase verification", "approvals", "#5B4B8A", "approvals"),
]


def _home_date_label(today: date | None = None) -> str:
    day = today or date.today()
    return day.strftime("%a, %d %b %Y")


class HomeScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "home"
        self.md_bg_color = theme.BG

        root = MDBoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))

        hero = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(56), spacing=dp(8))
        hero_copy = MDBoxLayout(orientation="vertical", spacing=dp(2))
        self.welcome_label = MDLabel(
            text="Welcome Back!",
            font_style="H5",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.LOGIN_NAVY,
            size_hint_y=None,
            height=dp(30),
        )
        hero_copy.add_widget(self.welcome_label)
        hero_copy.add_widget(
            MDLabel(
                text="Here's what's happening today.",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(20),
            )
        )
        hero.add_widget(hero_copy)
        date_wrap = MDCard(
            orientation="vertical",
            size_hint_x=None,
            width=dp(128),
            size_hint_y=None,
            height=dp(36),
            md_bg_color=theme.SURFACE,
            radius=[dp(18)],
            padding=[dp(8), dp(6), dp(8), dp(6)],
            elevation=0,
            line_color=theme.LOGIN_GOLD,
            line_width=1.5,
        )
        self.date_pill = MDLabel(
            text=_home_date_label(),
            theme_text_color="Custom",
            text_color=theme.LOGIN_NAVY,
            bold=True,
            font_style="Caption",
            halign="center",
            valign="middle",
        )
        date_wrap.add_widget(self.date_pill)
        hero.add_widget(date_wrap)
        root.add_widget(hero)

        summary = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(96),
            md_bg_color=theme.SURFACE,
            radius=[dp(16)],
            padding=dp(8),
            elevation=1,
        )
        pending_col = MDBoxLayout(orientation="vertical", spacing=dp(4))
        self.pending_value = MDLabel(
            text="—",
            font_style="H4",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.LOGIN_GOLD,
            halign="center",
            size_hint_y=None,
            height=dp(42),
        )
        pending_col.add_widget(self.pending_value)
        pending_col.add_widget(
            MDLabel(
                text="Pending Approvals",
                theme_text_color="Custom",
                text_color=theme.LOGIN_NAVY,
                bold=True,
                font_style="Caption",
                halign="center",
                size_hint_y=None,
                height=dp(20),
            )
        )
        approved_col = MDBoxLayout(orientation="vertical", spacing=dp(4))
        self.approved_value = MDLabel(
            text="—",
            font_style="H4",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.SUCCESS,
            halign="center",
            size_hint_y=None,
            height=dp(42),
        )
        approved_col.add_widget(self.approved_value)
        approved_col.add_widget(
            MDLabel(
                text="Approved",
                theme_text_color="Custom",
                text_color=theme.LOGIN_NAVY,
                bold=True,
                font_style="Caption",
                halign="center",
                size_hint_y=None,
                height=dp(20),
            )
        )
        summary.add_widget(pending_col)
        summary.add_widget(approved_col)
        root.add_widget(summary)

        # Keep for notification text updates from older hooks / API status.
        self.notif_label = MDLabel(
            text="",
            opacity=0,
            size_hint_y=None,
            height=0,
        )
        root.add_widget(self.notif_label)

        scroll = MDScrollView()
        self.cards = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            size_hint_y=None,
            padding=(0, 0, 0, dp(12)),
        )
        self.cards.bind(minimum_height=self.cards.setter("height"))
        self._summary_card = summary
        self.apply_access(getattr(self.app, "access", None) or {})

        scroll.add_widget(self.cards)
        root.add_widget(scroll)
        root.add_widget(
            MDLabel(
                text="Secure & Trusted",
                theme_text_color="Custom",
                text_color=theme.LOGIN_NAVY,
                bold=True,
                font_style="Caption",
                halign="center",
                size_hint_y=None,
                height=dp(28),
            )
        )
        self.add_widget(root)

    def apply_access(self, access: dict | None) -> None:
        access = dict(access or {})
        if hasattr(self, "_summary_card") and self._summary_card is not None:
            self._summary_card.opacity = 1 if can_access(access, "approvals") else 0
            self._summary_card.disabled = not can_access(access, "approvals")
            self._summary_card.height = dp(96) if can_access(access, "approvals") else 0
        if not hasattr(self, "cards") or self.cards is None:
            return
        self.cards.clear_widgets()
        for group, title, subtitle, screen, accent, access_key in _HOME_MODULES:
            if not can_access(access, access_key):
                continue
            if group:
                self.cards.add_widget(
                    MDLabel(
                        text=str(group).upper(),
                        font_style="Caption",
                        theme_text_color="Custom",
                        text_color=theme.TEXT_MUTED,
                        bold=True,
                        size_hint_y=None,
                        height=dp(28),
                        padding=(dp(4), dp(8), 0, 0),
                    )
                )
            card = ModuleCard(title=title, subtitle=subtitle, accent_color=accent)
            card.bind(on_release=lambda *_a, s=screen: self.app.shell.navigate(s))
            self.cards.add_widget(card)

    def on_workspace_enter(self) -> None:
        self.apply_access(getattr(self.app, "access", None) or {})
        self._refresh_welcome()
        self.date_pill.text = _home_date_label()
        self._load_summary()
        self._load_notifications()

    def _refresh_welcome(self) -> None:
        raw = ""
        try:
            raw = str(getattr(self.app, "display_name", "") or getattr(self.app.api, "username", "") or "").strip()
        except Exception:
            raw = ""
        if not raw:
            self.welcome_label.text = "Welcome Back!"
            return
        name = " ".join(part.capitalize() for part in raw.replace("_", " ").split())
        self.welcome_label.text = f"Welcome Back, {name}!"

    def _load_summary(self) -> None:
        def work():
            pending = approvals_api.fetch_outstanding(self.app.api)
            approved = approvals_api.fetch_history(self.app.api)
            return pending, approved

        def ok(payload):
            pending, approved = payload
            self.pending_value.text = str(len(pending or []))
            self.approved_value.text = str(len(approved or []))

        def err(_exc):
            self.pending_value.text = "—"
            self.approved_value.text = "—"

        run_async(work, on_success=ok, on_error=err)

    def _load_notifications(self) -> None:
        def work():
            return notifications_api.fetch_notifications(self.app.api)

        def ok(items):
            if not items:
                self.notif_label.text = "Notifications: none"
                return
            self.notif_label.text = f"Notifications: {len(items)} — {items[0].title}"

        def err(_exc):
            self.notif_label.text = "Notifications unavailable"
            toast("Notifications unavailable")

        run_async(work, on_success=ok, on_error=err)
