"""Home module launcher + live approvals summary — white cards, blue outline icons."""

from __future__ import annotations

from datetime import date

from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
from kivy.graphics import Color, Ellipse, Line, Rectangle, RoundedRectangle, Triangle
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.card import MDCard
from kivymd.uix.gridlayout import MDGridLayout
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView

from hbe_mobile import theme
from hbe_mobile.api import approvals as approvals_api
from hbe_mobile.api import notifications as notifications_api
from hbe_mobile.utils.async_jobs import run_async
from hbe_mobile.utils.nav import can_access


# group, title, iconly glyph key, navigate screen, access key
_HOME_MODULES = [
    (None, "Dashboard", "dashboard", "dashboard", "main_dashboard"),
    ("Purchase & Inventory", "Indent Request", "indent_request", "indent_request", "indent_request"),
    (None, "Indent Approval", "indent_approval", "indent_approvals", "indent_approvals"),
    ("Restaurant", "POS", "rest_pos", "pos_invoice", "pos"),
    (None, "KOT", "rest_kot", "kot", "kot"),
    ("Bar", "POS", "bar_pos", "pos_bar_invoice", "pos_bar"),
    (None, "KOT", "bar_kot", "kot_bar", "kot_bar"),
    ("Employee Payroll", "Employee", "employee", "payroll_employees", "payroll_employee"),
    (None, "Attendance", "attendance", "payroll_attendance", "payroll_attendance"),
    (None, "Credit", "credit", "payroll_credit", "payroll_credit"),
    (None, "Tips", "tips", "payroll_tips", "payroll_tips"),
    ("Accounts", "Approvals", "approvals", "approvals", "approvals"),
]

# Uniform outline icons: #1877F2 on every Home tile (card language, not discs).
_BLUE = (24 / 255, 119 / 255, 242 / 255, 1.0)  # #1877F2
_BLUE_FILL = _BLUE
_GOLD = _BLUE
_GOLD_FILL = _BLUE
_TERRACOTTA = _BLUE
_TERRACOTTA_FILL = _BLUE
_WINE = _BLUE
_WINE_FILL = _BLUE
_TEAL = _BLUE
_TEAL_FILL = _BLUE
_GREEN = _BLUE
_GREEN_FILL = _BLUE
_RING = (238 / 255, 241 / 255, 244 / 255, 1.0)  # unused; tiles are cards now

_KIND_INK = {
    "dashboard": (_BLUE, _BLUE),
    "indent_request": (_BLUE, _BLUE),
    "indent_approval": (_BLUE, _BLUE),
    "rest_pos": (_BLUE, _BLUE),
    "rest_kot": (_BLUE, _BLUE),
    "bar_pos": (_BLUE, _BLUE),
    "bar_kot": (_BLUE, _BLUE),
    "employee": (_BLUE, _BLUE),
    "attendance": (_BLUE, _BLUE),
    "credit": (_BLUE, _BLUE),
    "tips": (_BLUE, _BLUE),
    "approvals": (_BLUE, _BLUE),
}


def _home_date_label(today: date | None = None) -> str:
    day = today or date.today()
    return day.strftime("%a, %d %b %Y")


class _GoldRule(Widget):
    """Short 32×2 gold rule under the welcome block (left-aligned)."""

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


class _IconDisc(Widget):
    """36dp outline glyph in #1877F2; the white card lives on the tile, not a disc."""

    def __init__(self, kind: str, **kwargs):
        super().__init__(**kwargs)
        self.kind = kind
        self.size_hint = (None, None)
        self.size = (dp(36), dp(36))
        self.bind(pos=self._redraw, size=self._redraw)

    def _space(self):
        gs = min(self.width, self.height)
        ox = self.x + (self.width - gs) / 2.0
        oy = self.y + (self.height - gs) / 2.0
        s = gs / 24.0
        return ox, oy, s

    def _xy(self, x, y):
        ox, oy, s = self._space()
        return ox + x * s, oy + (24.0 - y) * s

    def _box(self, x, y, w, h):
        ox, oy, s = self._space()
        return ox + x * s, oy + (24.0 - y - h) * s, w * s, h * s

    def _sw(self):
        # Kivy Line width is half-stroke; 2.4/24 of the 24dp glyph.
        return max(0.7, 1.2 * self._space()[2])

    def _palette(self):
        return _KIND_INK.get(self.kind, (_GOLD, _GOLD_FILL))

    def _ink(self):
        # MDIcon Custom icon_color: section stroke (same hue for every item in the section).
        return self._palette()[0]

    def _tone(self):
        # Slightly deeper two-tone fill, same hue as the stroke.
        return self._palette()[1]

    def _line(self, pts, close=False, color=None):
        Color(*(color or self._ink()))
        out = []
        it = iter(pts)
        for x in it:
            y = next(it)
            out.extend(self._xy(x, y))
        Line(points=out, width=self._sw(), cap="round", joint="round", close=close)

    def _rrect(self, x, y, w, h, r, fill=None):
        bx, by, bw, bh = self._box(x, y, w, h)
        rr = r * self._space()[2]
        if fill:
            Color(*fill)
            RoundedRectangle(pos=(bx, by), size=(bw, bh), radius=[rr])
        Color(*self._ink())
        Line(
            rounded_rectangle=(bx, by, bw, bh, rr),
            width=self._sw(),
            cap="round",
            joint="round",
        )

    def _fill_rrect(self, x, y, w, h, r, color=None):
        bx, by, bw, bh = self._box(x, y, w, h)
        rr = r * self._space()[2]
        Color(*(color or self._tone()))
        RoundedRectangle(pos=(bx, by), size=(bw, bh), radius=[rr])

    def _circle(self, cx, cy, r, fill=None):
        x, y = self._xy(cx, cy)
        rr = r * self._space()[2]
        if fill:
            Color(*fill)
            Ellipse(pos=(x - rr, y - rr), size=(2 * rr, 2 * rr))
        Color(*self._ink())
        Line(circle=(x, y, rr), width=self._sw(), cap="round")

    def _dot(self, cx, cy, r, color=None):
        Color(*(color or self._tone()))
        x, y = self._xy(cx, cy)
        rr = r * self._space()[2]
        Ellipse(pos=(x - rr, y - rr), size=(2 * rr, 2 * rr))

    def _poly_fill(self, pts, color=None):
        Color(*(color or self._tone()))
        pairs = list(zip(pts[0::2], pts[1::2]))
        cx = sum(p[0] for p in pairs) / len(pairs)
        cy = sum(p[1] for p in pairs) / len(pairs)
        ocx, ocy = self._xy(cx, cy)
        n = len(pairs)
        for i in range(n):
            x1, y1 = self._xy(*pairs[i])
            x2, y2 = self._xy(*pairs[(i + 1) % n])
            Triangle(points=[ocx, ocy, x1, y1, x2, y2])

    def _redraw(self, *_args):
        self.canvas.clear()
        with self.canvas:
            self._paint_disc()
            fn = getattr(self, f"_g_{self.kind}", None)
            if fn:
                fn()

    def _paint_disc(self):
        # Card chrome is on _IconTile; glyphs sit on a transparent field.
        return

    def _g_dashboard(self):
        self._rrect(4.2, 11.5, 4.4, 8.0, 2.2)
        self._rrect(9.8, 4.6, 4.4, 14.9, 2.2)
        self._rrect(15.4, 8.4, 4.4, 11.1, 2.2)

    def _g_indent_request(self):
        # Inventory crate + plus: a stock request, not another clipboard.
        self._rrect(4.3, 8.8, 15.4, 10.8, 1.8)
        self._line([4.3, 12.5, 19.7, 12.5])
        self._line([8.5, 8.8, 12.0, 5.1, 15.5, 8.8])
        self._line([12.0, 14.4, 12.0, 18.0])
        self._line([10.2, 16.2, 13.8, 16.2])

    def _g_indent_approval(self):
        # Clipboard with a check: approve the indent, not a crate.
        self._rrect(5.6, 5.4, 12.8, 15.0, 2.2)
        self._rrect(8.6, 3.2, 6.8, 4.0, 1.2)
        self._line([8.6, 13.4, 11.0, 15.8, 16.0, 10.6])

    def _g_rest_pos(self):
        self._line([6.4, 3.6, 6.4, 9.8])
        self._line([8.3, 3.6, 8.3, 9.8])
        self._line([10.2, 3.6, 10.2, 9.8])
        self._line([6.4, 9.8, 6.6, 11.4, 8.3, 12.5, 10.0, 11.4, 10.2, 9.8])
        self._line([8.3, 12.5, 8.3, 20.4])
        self._rrect(13.85, 3.9, 4.7, 7.0, 2.35)
        self._line([16.2, 10.9, 16.2, 20.4])

    def _g_rest_kot(self):
        self._line([6.6, 3.4, 17.4, 3.4, 17.4, 17.6, 16.05, 19.3, 14.7, 17.6, 13.35, 19.3, 12.0, 17.6, 10.65, 19.3, 9.3, 17.6, 7.95, 19.3, 6.6, 17.6], close=True)
        self._line([9.2, 8.2, 14.8, 8.2])
        self._line([9.2, 11.6, 14.8, 11.6])
        self._line([9.2, 15.0, 13.0, 15.0])

    def _g_bar_pos(self):
        bowl = [
            8.2, 4.2, 15.8, 4.2, 15.05, 10.7,
            14.5, 12.5, 13.4, 13.9, 12.0, 14.8,
            10.6, 13.9, 9.5, 12.5, 8.95, 10.7,
        ]
        self._line(bowl, close=True)
        self._line([12, 14.8, 12, 19.7])
        self._line([8.6, 19.7, 15.4, 19.7])

    def _g_bar_kot(self):
        tri = [6.4, 4.4, 17.6, 4.4, 12.0, 13.2]
        self._line(tri, close=True)
        self._line([12, 13.2, 12, 19.7])
        self._line([8.5, 19.7, 15.5, 19.7])
        self._dot(16.7, 5.4, 1.15, color=self._tone())

    def _g_employee(self):
        self._circle(9.0, 8.0, 2.55)
        self._line([4.7, 18.6, 5.4, 15.2, 6.8, 13.7, 9.0, 13.5, 11.2, 13.7, 12.6, 15.2, 13.3, 18.6])
        self._circle(16.1, 8.5, 2.05)
        self._line([13.5, 18.6, 13.9, 16.5, 15.0, 15.4, 16.2, 15.3, 17.4, 15.8, 18.7, 16.8])

    def _g_attendance(self):
        self._rrect(4.2, 6.0, 15.6, 13.8, 2.6)
        self._line([4.2, 10.4, 19.8, 10.4])
        self._line([8.2, 3.8, 8.2, 8.0])
        self._line([15.8, 3.8, 15.8, 8.0])
        self._line([8.6, 15.5, 10.8, 17.5, 15.5, 12.5], color=self._tone())

    def _g_credit(self):
        self._rrect(3.4, 6.4, 17.2, 11.4, 2.6)
        self._line([3.4, 10.6, 20.6, 10.6])
        self._rrect(6.0, 7.4, 3.8, 2.3, 0.55)
        self._line([6.6, 14.8, 11.0, 14.8])

    def _g_tips(self):
        star = [
            12.0, 3.5, 14.1, 9.15, 19.95, 9.15, 15.25, 12.55, 17.05, 18.1,
            12.0, 14.85, 6.95, 18.1, 8.75, 12.55, 4.05, 9.15, 9.9, 9.15,
        ]
        self._line(star, close=True)

    def _g_approvals(self):
        shield = [
            12.0, 3.2, 5.3, 6.15, 5.3, 11.7,
            6.2, 15.4, 8.5, 18.2, 12.0, 20.9,
            15.5, 18.2, 17.8, 15.4, 18.7, 11.7, 18.7, 6.15,
        ]
        self._line(shield, close=True)
        self._line([8.55, 12.2, 10.9, 14.55, 15.6, 9.5], color=self._tone())


class _IconTile(ButtonBehavior, MDBoxLayout):
    """White rounded card with a blue outline icon and a dark label."""

    def __init__(self, title: str, glyph: str, compact: bool = False, **kwargs):
        super().__init__(**kwargs)
        self.orientation = "vertical"
        self.size_hint_y = None
        self.height = dp(112)
        self.spacing = dp(8)
        self.padding = [dp(6), dp(16), dp(6), dp(12)]
        self.md_bg_color = (0, 0, 0, 0)
        with self.canvas.before:
            Color(24 / 255, 119 / 255, 242 / 255, 0.08)
            self._shadow = RoundedRectangle(radius=[dp(18)])
            Color(1, 1, 1, 1)
            self._card = RoundedRectangle(radius=[dp(18)])
        self.bind(pos=self._sync_card, size=self._sync_card)
        self.add_widget(_IconDisc(glyph, pos_hint={"center_x": 0.5}))
        label = MDLabel(
            text=title,
            font_style="Caption",
            halign="center",
            valign="top",
            theme_text_color="Custom",
            text_color=theme.TEXT,
            size_hint_y=None,
            height=dp(32),
            bold=True,
        )
        label.bind(width=lambda inst, w: setattr(inst, "text_size", (w, None)))
        self.add_widget(label)

    def _sync_card(self, *_args):
        self._shadow.pos = (self.x, self.y - dp(2))
        self._shadow.size = (self.width, self.height)
        self._card.pos = (self.x, self.y)
        self._card.size = (self.width, self.height)


def _section_label(text: str) -> MDLabel:
    return MDLabel(
        text=text,
        font_style="Subtitle1",
        bold=True,
        theme_text_color="Custom",
        text_color=theme.TEXT,
        size_hint_y=None,
        height=dp(32),
        padding=(0, dp(10), 0, 0),
    )


def _new_grid(cols: int = 2) -> MDGridLayout:
    grid = MDGridLayout(
        cols=cols,
        adaptive_height=True,
        spacing=dp(12),
        size_hint_y=None,
        padding=(0, 0, 0, dp(4)),
    )
    return grid


class HomeScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "home"
        self.md_bg_color = theme.BG

        root = MDBoxLayout(orientation="vertical", padding=[dp(20), dp(12), dp(20), dp(8)], spacing=dp(10))

        hero = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(92), spacing=dp(0))
        hero.add_widget(
            MDLabel(
                text="Welcome",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
            )
        )
        self.welcome_label = MDLabel(
            text="",
            font_style="H5",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.TEXT,
            size_hint_y=None,
            height=dp(34),
        )
        hero.add_widget(self.welcome_label)
        self.date_pill = MDLabel(
            text=_home_date_label(),
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            font_style="Caption",
            size_hint_y=None,
            height=dp(20),
        )
        hero.add_widget(self.date_pill)
        hero.add_widget(_GoldRule())
        root.add_widget(hero)

        chips = MDBoxLayout(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(36),
            spacing=dp(8),
        )
        pending_chip = MDCard(
            orientation="horizontal",
            size_hint=(None, None),
            width=dp(112),
            height=dp(32),
            md_bg_color=theme.SURFACE,
            radius=[dp(20)],
            padding=[dp(12), 0, dp(12), 0],
            spacing=dp(6),
            elevation=0,
            line_color="#E2E8F0",
            line_width=1,
        )
        pending_chip.add_widget(
            MDLabel(
                text="Pending",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                valign="middle",
            )
        )
        self.pending_value = MDLabel(
            text="—",
            font_style="Caption",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.LOGIN_GOLD,
            halign="right",
            valign="middle",
            size_hint_x=None,
            width=dp(28),
        )
        pending_chip.add_widget(self.pending_value)
        approved_chip = MDCard(
            orientation="horizontal",
            size_hint=(None, None),
            width=dp(118),
            height=dp(32),
            md_bg_color=theme.SURFACE,
            radius=[dp(20)],
            padding=[dp(12), 0, dp(12), 0],
            spacing=dp(6),
            elevation=0,
            line_color="#E2E8F0",
            line_width=1,
        )
        approved_chip.add_widget(
            MDLabel(
                text="Approved",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                valign="middle",
            )
        )
        self.approved_value = MDLabel(
            text="—",
            font_style="Caption",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.ACCENT,
            halign="right",
            valign="middle",
            size_hint_x=None,
            width=dp(28),
        )
        approved_chip.add_widget(self.approved_value)
        chips.add_widget(pending_chip)
        chips.add_widget(approved_chip)
        self._summary_card = chips
        root.add_widget(chips)

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
            spacing=dp(4),
            size_hint_y=None,
            padding=(0, 0, 0, dp(16)),
        )
        self.cards.bind(minimum_height=self.cards.setter("height"))
        self.apply_access(getattr(self.app, "access", None) or {})

        scroll.add_widget(self.cards)
        root.add_widget(scroll)
        self.add_widget(root)

    def apply_access(self, access: dict | None) -> None:
        access = dict(access or {})
        if hasattr(self, "_summary_card") and self._summary_card is not None:
            allowed = can_access(access, "approvals")
            self._summary_card.opacity = 1 if allowed else 0
            self._summary_card.disabled = not allowed
            self._summary_card.height = dp(36) if allowed else 0
        if not hasattr(self, "cards") or self.cards is None:
            return
        self.cards.clear_widgets()
        grid = None
        for group, title, glyph, screen, access_key in _HOME_MODULES:
            if not can_access(access, access_key):
                continue
            if group or grid is None:
                if group:
                    self.cards.add_widget(_section_label(str(group)))
                cols = 2
                grid = _new_grid(cols)
                self.cards.add_widget(grid)
            tile = _IconTile(title=title, glyph=glyph)
            tile.bind(on_release=lambda *_a, s=screen: self.app.shell.navigate(s))
            grid.add_widget(tile)

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
            self.welcome_label.text = "Welcome"
            return
        name = " ".join(part.capitalize() for part in raw.replace("_", " ").split())
        self.welcome_label.text = name

    def _load_summary(self) -> None:
        if not can_access(getattr(self.app, "access", None) or {}, "approvals"):
            self.pending_value.text = "—"
            self.approved_value.text = "—"
            return

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
