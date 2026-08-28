"""Workspace shell: overlay side nav + content ScreenManager (no MDNavigationDrawer).

Drawer slides over content (modern mobile pattern) so the main panel never shrinks.
MDNavigationDrawer/MDTopAppBar are avoided — they pull SDL2 WindowController, which
is unavailable on some Kivy pygame builds (e.g. Python 3.14 wheels).
"""

from __future__ import annotations

from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.screenmanager import ScreenManager
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDIconButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView

from hbe_mobile import theme
from hbe_mobile.utils.nav import NAV_ITEMS, can_access, filter_nav_items
from hbe_mobile.widgets.nav_item import NavItem


class _Scrim(ButtonBehavior, Widget):
    """Dimmed overlay that closes the drawer when tapped."""

    def __init__(self, on_tap, **kwargs):
        super().__init__(**kwargs)
        self._on_tap = on_tap
        with self.canvas.before:
            self._color = Color(0.06, 0.11, 0.19, 0.52)
            self._rect = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._sync, size=self._sync)

    def _sync(self, *_args) -> None:
        self._rect.pos = self.pos
        self._rect.size = self.size

    def on_release(self) -> None:
        if self._on_tap:
            self._on_tap()


class WorkspaceShell(MDScreen):
    """Authenticated chrome shared by Home / Dashboard / Products / POS / Approvals."""

    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "workspace"
        self._nav_items: dict[str, NavItem] = {}
        self._nav_group_labels: list = []
        self._nav_open = False
        self._active_screen = "home"
        self._nav_width = dp(260)
        self._access: dict = {}
        self._nav_box = None

        root = MDBoxLayout(orientation="vertical", md_bg_color=theme.BG)

        top = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(52),
            padding=[dp(4), dp(4), dp(8), dp(4)],
            md_bg_color=theme.TOPBAR_BG,
            spacing=dp(4),
        )
        top.add_widget(
            MDIconButton(
                icon="menu",
                theme_icon_color="Custom",
                icon_color=theme.TOPBAR_FG,
                on_release=lambda *_: self.toggle_nav(),
            )
        )
        self.title_label = MDLabel(
            text="Hotel Bell Elite",
            theme_text_color="Custom",
            text_color=theme.TOPBAR_FG,
            bold=True,
            font_style="H6",
            halign="center",
        )
        top.add_widget(self.title_label)
        top.add_widget(
            MDIconButton(
                icon="logout",
                theme_icon_color="Custom",
                icon_color=theme.TOPBAR_FG,
                on_release=lambda *_: self.app.logout(),
            )
        )
        root.add_widget(top)

        # Gold rule under topbar (Home mock ornament)
        gold_rule = MDBoxLayout(size_hint_y=None, height=dp(2), md_bg_color=theme.LOGIN_GOLD)
        root.add_widget(gold_rule)

        stage = FloatLayout(size_hint=(1, 1))

        self.content_manager = ScreenManager(size_hint=(1, 1))
        stage.add_widget(self.content_manager)

        self.scrim = _Scrim(on_tap=self.close_nav, size_hint=(1, 1))
        self.scrim.opacity = 0
        self.scrim.disabled = True
        stage.add_widget(self.scrim)

        self.nav_panel = MDBoxLayout(
            orientation="vertical",
            size_hint=(None, 1),
            width=self._nav_width,
            md_bg_color=theme.SURFACE,
            padding=dp(8),
            spacing=dp(4),
        )
        brand = MDLabel(
            text="Hotel Bell Elite",
            font_style="H6",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.TEXT,
            size_hint_y=None,
            height=dp(40),
        )
        self.nav_panel.add_widget(brand)
        scroll = MDScrollView()
        nav_box = MDBoxLayout(
            orientation="vertical",
            adaptive_height=True,
            spacing=dp(4),
            size_hint_y=None,
        )
        nav_box.bind(minimum_height=nav_box.setter("height"))
        self._nav_box = nav_box
        self._rebuild_nav(NAV_ITEMS)

        scroll.add_widget(nav_box)
        self.nav_panel.add_widget(scroll)
        self.nav_panel.add_widget(
            MDRaisedButton(
                text="Logout",
                md_bg_color="#FDECEC",
                theme_text_color="Custom",
                text_color="#E11D48",
                size_hint_y=None,
                height=dp(48),
                on_release=lambda *_: self._logout_from_nav(),
            )
        )
        stage.add_widget(self.nav_panel)
        stage.bind(size=self._sync_drawer_geometry, pos=self._sync_drawer_geometry)

        root.add_widget(stage)
        self.add_widget(root)
        self.bind(size=self._sync_drawer_geometry)

    def _rebuild_nav(self, items: list) -> None:
        if not self._nav_box:
            return
        self._nav_box.clear_widgets()
        self._nav_items.clear()
        current_group = object()
        for item in items:
            group = item.get("group")
            if group and group != current_group:
                current_group = group
                self._nav_box.add_widget(
                    MDLabel(
                        text=str(group).upper(),
                        font_style="Caption",
                        theme_text_color="Custom",
                        text_color=theme.TEXT_MUTED,
                        size_hint_y=None,
                        height=dp(28),
                        padding=(dp(8), dp(8)),
                    )
                )
            nav = NavItem(label=item["label"])
            screen_name = item["screen"]
            nav.bind(on_release=lambda *_a, s=screen_name: self.navigate(s))
            self._nav_items[screen_name] = nav
            self._nav_box.add_widget(nav)

    def apply_access(self, access: dict | None) -> None:
        self._access = dict(access or {})
        self._rebuild_nav(filter_nav_items(self._access))
        home = None
        try:
            home = self.content_manager.get_screen("home")
        except Exception:
            home = None
        if home and hasattr(home, "apply_access"):
            home.apply_access(self._access)
        if self._active_screen not in self._nav_items and self._active_screen != "home":
            self.navigate("home")

    def _logout_from_nav(self) -> None:
        self.close_nav()
        self.app.logout()

    def _sync_drawer_geometry(self, *_args) -> None:
        # Keep drawer full-height on the left; park it off-screen when closed.
        self.nav_panel.height = self.scrim.height or self.height
        self.nav_panel.y = self.scrim.y
        if self._nav_open:
            self.nav_panel.x = self.scrim.x
        else:
            self.nav_panel.x = self.scrim.x - self.nav_panel.width

    def open_nav(self) -> None:
        self._nav_open = True
        self.scrim.opacity = 1
        self.scrim.disabled = False
        self._sync_drawer_geometry()

    def close_nav(self) -> None:
        self._nav_open = False
        self.scrim.opacity = 0
        self.scrim.disabled = True
        self._sync_drawer_geometry()

    def toggle_nav(self) -> None:
        if self._nav_open:
            self.close_nav()
        else:
            self.open_nav()

    def register_screens(self, screens: dict) -> None:
        for name, screen in screens.items():
            if screen.parent:
                continue
            screen.name = name
            self.content_manager.add_widget(screen)

    def navigate(self, screen_name: str) -> None:
        if screen_name not in self.content_manager.screen_names:
            return
        item = next((i for i in NAV_ITEMS if i["screen"] == screen_name), None)
        if item and not can_access(self._access, str(item.get("access_key") or "")):
            screen_name = "home"
        self.content_manager.current = screen_name
        self._active_screen = screen_name
        self.title_label.text = "Hotel Bell Elite"
        for name, nav in self._nav_items.items():
            nav.is_active = name == screen_name
        self.close_nav()
        screen = self.content_manager.get_screen(screen_name)
        if hasattr(screen, "on_workspace_enter"):
            screen.on_workspace_enter()
