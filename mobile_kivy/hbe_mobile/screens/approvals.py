"""Accounts Approvals — pending list + verify / history revert + purchase detail."""

from __future__ import annotations

from kivy.clock import Clock
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.toast import toast

from hbe_mobile import theme
from hbe_mobile.api import approvals as approvals_api
from hbe_mobile.models import OutstandingExpense, VerificationEntry
from hbe_mobile.utils.async_jobs import run_async


def _inr(amount: float) -> str:
    try:
        return f"₹{amount:,.0f}" if float(amount).is_integer() else f"₹{amount:,.2f}"
    except (TypeError, ValueError):
        return f"₹{amount}"


# Universal blue — local to this screen (do not change global theme.ACCENT).
_AP_ACCENT = "#1877F2"
_AP_ACCENT_PRESS = "#1565C0"
_AP_ACCENT_SOFT = "#E8F1FE"
_CHIP_BORDER = "#E2E8F0"
_CARD_LINE = "#EEF1F4"
_WHITE = "#FFFFFF"


class _TapCard(ButtonBehavior, MDCard):
    """Card that opens detail when tapped (Approve/Revert stay on their own buttons)."""


class _GoldRule(Widget):
    """Short 32×2 gold rule under the Approvals title (left-aligned)."""

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


class _ApChip(ButtonBehavior, MDCard):
    """32dp KOT-style pill — Pending / Approved / Back / Filter."""

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
            text=caption,
            halign="center",
            valign="middle",
            theme_text_color="Custom",
            text_color=theme.TEXT,
            font_style="Caption",
            bold=True,
        )
        self.add_widget(self._caption)
        self.set_caption(caption)
        self.set_selected(False)

    def set_caption(self, caption: str) -> None:
        self._caption.text = caption
        self.width = max(dp(88), dp(28) + len(caption) * dp(7.4))

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.md_bg_color = _AP_ACCENT
            self.line_color = _AP_ACCENT
            self._caption.text_color = _WHITE
        else:
            self.md_bg_color = theme.SURFACE
            self.line_color = _CHIP_BORDER
            self._caption.text_color = theme.TEXT

    def on_release(self):
        if self._on_press:
            self._on_press()


class ApprovalsScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "approvals"
        self.md_bg_color = theme.BG
        self._outstanding: list[OutstandingExpense] = []
        self._mode = "outstanding"
        self._pending_count: int | None = None
        self._approved_count: int | None = None
        self._poll_ev = None
        self._busy = False
        self._fingerprint = ""
        self._detail_open = False
        self._detail_expense: OutstandingExpense | None = None

        root = MDBoxLayout(
            orientation="vertical",
            padding=[dp(20), dp(12), dp(20), dp(16)],
            spacing=dp(8),
        )

        self.back_btn = _ApChip("Back", lambda: self._close_detail())
        self.back_btn.opacity = 0
        self.back_btn.disabled = True
        self.back_btn.height = 0
        root.add_widget(self.back_btn)

        self.head = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(36), spacing=dp(0))
        self.title_label = MDLabel(
            text="Approvals",
            font_style="H5",
            bold=True,
            theme_text_color="Custom",
            text_color=theme.TEXT,
            size_hint_y=None,
            height=dp(36),
        )
        self.head.add_widget(self.title_label)
        root.add_widget(self.head)
        self.gold_rule = _GoldRule()
        root.add_widget(self.gold_rule)

        self.status = MDLabel(
            text="",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            font_style="Caption",
            size_hint_y=None,
            height=dp(18),
        )
        root.add_widget(self.status)

        self.tabs = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(8))
        self.btn_pending = _ApChip("Pending", lambda: self._show_outstanding())
        self.btn_approved = _ApChip("Approved", lambda: self._show_history())
        self.btn_pending.set_selected(True)
        self.tabs.add_widget(self.btn_pending)
        self.tabs.add_widget(self.btn_approved)
        root.add_widget(self.tabs)

        # Quiet placeholder matching HTML #approvals-summary (status lives under gold rule).
        self.summary = MDCard(
            orientation="vertical",
            size_hint_y=None,
            height=0,
            padding=0,
            radius=[dp(20)],
            md_bg_color=theme.SURFACE,
            elevation=0,
            opacity=0,
        )

        scroll = MDScrollView()
        self.list = MDBoxLayout(
            orientation="vertical",
            adaptive_height=True,
            spacing=dp(10),
            size_hint_y=None,
            padding=[0, 0, 0, dp(16)],
        )
        self.list.bind(minimum_height=self.list.setter("height"))
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_leave(self, *args) -> None:
        self._stop_auto_refresh()
        self._detail_open = False
        return super().on_leave(*args)

    def _stop_auto_refresh(self) -> None:
        if self._poll_ev is not None:
            self._poll_ev.cancel()
            self._poll_ev = None

    def _start_auto_refresh(self) -> None:
        self._stop_auto_refresh()
        self._poll_ev = Clock.schedule_interval(lambda *_: self._silent_refresh(), 4.0)

    def _silent_refresh(self) -> None:
        if self._busy or self._detail_open or not self.parent:
            return
        if self._mode == "history":
            self._show_history(silent=True)
        else:
            self._show_outstanding(silent=True)

    def on_workspace_enter(self) -> None:
        self._close_detail(refresh=False)
        if self._mode == "history":
            self._show_history()
        else:
            self._show_outstanding()
        self._start_auto_refresh()

    def _set_list_chrome_visible(self, visible: bool) -> None:
        self.tabs.height = dp(36) if visible else 0
        self.tabs.opacity = 1 if visible else 0
        self.tabs.disabled = not visible
        self.status.height = dp(18) if visible else 0
        self.status.opacity = 1 if visible else 0
        self.summary.height = 0
        self.summary.opacity = 0
        self.back_btn.height = 0 if visible else dp(32)
        self.back_btn.opacity = 0 if visible else 1
        self.back_btn.disabled = visible
        self.title_label.text = "Approvals" if visible else "Purchase detail"
        self.head.height = dp(36)

    def _close_detail(self, *, refresh: bool = True) -> None:
        self._detail_open = False
        self._detail_expense = None
        self._set_list_chrome_visible(True)
        if refresh:
            if self._mode == "history":
                self._show_history()
            else:
                self._show_outstanding()

    def _set_mode_buttons(self, mode: str) -> None:
        pending = mode == "outstanding"
        p = "—" if self._pending_count is None else str(self._pending_count)
        a = "—" if self._approved_count is None else str(self._approved_count)
        self.btn_pending.set_caption(f"Pending {p}")
        self.btn_approved.set_caption(f"Approved {a}")
        self.btn_pending.set_selected(pending)
        self.btn_approved.set_selected(not pending)

    def _make_accent_bar(self, color: str | None = None) -> Widget:
        bar = Widget(size_hint_x=None, width=dp(3))
        accent = color or _AP_ACCENT
        with bar.canvas.before:
            from kivy.graphics import Color, RoundedRectangle

            Color(*self._hex_to_rgba(accent))
            bar._accent_rect = RoundedRectangle(  # type: ignore[attr-defined]
                pos=bar.pos,
                size=bar.size,
                radius=[dp(2), 0, 0, dp(2)],
            )

        def _sync(*_a):
            bar._accent_rect.pos = bar.pos  # type: ignore[attr-defined]
            bar._accent_rect.size = bar.size  # type: ignore[attr-defined]

        bar.bind(pos=_sync, size=_sync)
        return bar

    @staticmethod
    def _hex_to_rgba(hex_color: str) -> tuple[float, float, float, float]:
        h = hex_color.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return (r / 255.0, g / 255.0, b / 255.0, 1.0)

    def _add_pending_card(self, row: OutstandingExpense) -> None:
        card = _TapCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(128),
            padding=0,
            radius=[dp(20)],
            md_bg_color=theme.SURFACE,
            elevation=0,
            line_color=_CARD_LINE,
            line_width=1,
            on_release=lambda *_a, r=row: self._open_expense_detail(r),
        )
        card.add_widget(self._make_accent_bar())
        body = MDBoxLayout(orientation="vertical", padding=[dp(12), dp(10), dp(12), dp(10)], spacing=dp(4))
        top = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
        top.add_widget(
            MDLabel(
                text=str(row.expense_code or f"#{row.id}"),
                bold=True,
                theme_text_color="Custom",
                text_color=theme.TEXT,
            )
        )
        top.add_widget(
            MDLabel(
                text=_inr(row.balance),
                bold=True,
                halign="right",
                theme_text_color="Custom",
                text_color=_AP_ACCENT,
            )
        )
        body.add_widget(top)
        body.add_widget(
            MDLabel(
                text=f"{(row.supplier_name or '—').upper()} · {(row.description or '').upper()}",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
            )
        )
        foot = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(52), spacing=dp(8))
        foot.add_widget(
            MDLabel(
                text=row.sales_date or "—",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
            )
        )
        foot.add_widget(
            MDRaisedButton(
                text="Approve",
                md_bg_color=theme.SUCCESS_SOFT,
                theme_text_color="Custom",
                text_color=theme.SUCCESS,
                size_hint_x=None,
                width=dp(96),
                on_release=lambda *_a, r=row: self._approve_one(r),
            )
        )
        body.add_widget(foot)
        card.add_widget(body)
        self.list.add_widget(card)

    def _add_history_card(self, row: VerificationEntry) -> None:
        card = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(118),
            padding=0,
            radius=[dp(20)],
            md_bg_color=theme.SURFACE,
            elevation=0,
            line_color=_CARD_LINE,
            line_width=1,
        )
        card.add_widget(self._make_accent_bar())
        body = MDBoxLayout(orientation="vertical", padding=[dp(12), dp(10), dp(12), dp(10)], spacing=dp(4))
        top = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
        top.add_widget(
            MDLabel(
                text=f"#{row.id}",
                bold=True,
                theme_text_color="Custom",
                text_color=theme.TEXT,
            )
        )
        top.add_widget(
            MDLabel(
                text=_inr(row.total_amount),
                bold=True,
                halign="right",
                theme_text_color="Custom",
                text_color=_AP_ACCENT,
            )
        )
        body.add_widget(top)
        meta = " · ".join(
            part for part in [(row.supplier_name or "—").upper(), (row.expense_codes or "").upper()] if part
        )
        body.add_widget(
            MDLabel(
                text=meta,
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
            )
        )
        foot = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        foot.add_widget(
            MDLabel(
                text=row.payment_date or "—",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
            )
        )
        foot.add_widget(
            MDRaisedButton(
                text="Revert",
                md_bg_color=theme.WARN_SOFT,
                theme_text_color="Custom",
                text_color=theme.WARN,
                size_hint_x=None,
                width=dp(88),
                on_release=lambda *_a, pid=row.id: self._revert(pid),
            )
        )
        body.add_widget(foot)
        card.add_widget(body)
        self.list.add_widget(card)

    def _open_expense_detail(self, row: OutstandingExpense) -> None:
        self._detail_open = True
        self._detail_expense = row
        self._set_list_chrome_visible(False)
        self.list.clear_widgets()
        self.list.add_widget(
            MDLabel(
                text="Loading purchase details…",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                size_hint_y=None,
                height=dp(40),
            )
        )

        def work():
            return approvals_api.fetch_expense_detail(self.app.api, row.id)

        def ok(data: dict):
            if not self._detail_open:
                return
            self._render_expense_detail(data, fallback=row)

        def err(exc):
            if not self._detail_open:
                return
            self._render_expense_detail(
                {
                    "ok": True,
                    "expense": {
                        "id": row.id,
                        "expense_code": row.expense_code,
                        "sales_date": row.sales_date,
                        "description": row.description,
                        "amount": row.amount,
                        "balance": row.balance,
                        "supplier_id": row.supplier_id,
                        "supplier_name": row.supplier_name,
                        "category": row.category,
                        "invoice_number": "",
                        "payment_type": "",
                    },
                    "lines": [],
                    "stock_mode": "Purchase",
                    "source": "none",
                },
                fallback=row,
                error=str(exc),
            )

        run_async(work, ok, err)

    def _render_expense_detail(
        self, data: dict, *, fallback: OutstandingExpense, error: str = ""
    ) -> None:
        self.list.clear_widgets()
        expense = data.get("expense") if isinstance(data.get("expense"), dict) else {}
        lines = data.get("lines") if isinstance(data.get("lines"), list) else []
        stock_mode = str(data.get("stock_mode") or "Purchase")

        code = str(expense.get("expense_code") or fallback.expense_code or f"#{fallback.id}")
        balance = float(expense.get("balance") if expense.get("balance") is not None else fallback.balance)
        amount = float(expense.get("amount") if expense.get("amount") is not None else fallback.amount)
        supplier = str(expense.get("supplier_name") or fallback.supplier_name or "—")
        description = str(expense.get("description") or fallback.description or "")
        sales_date = str(expense.get("sales_date") or fallback.sales_date or "—")

        header = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(168),
            padding=0,
            radius=[dp(20)],
            md_bg_color=theme.SURFACE,
            elevation=0,
            line_color=_CARD_LINE,
            line_width=1,
        )
        header.add_widget(self._make_accent_bar())
        hbody = MDBoxLayout(orientation="vertical", padding=[dp(12), dp(10), dp(12), dp(10)], spacing=dp(4))
        top = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(24))
        top.add_widget(MDLabel(text=code, bold=True, theme_text_color="Custom", text_color=theme.TEXT))
        top.add_widget(
            MDLabel(
                text=_inr(balance),
                bold=True,
                halign="right",
                theme_text_color="Custom",
                text_color=_AP_ACCENT,
            )
        )
        hbody.add_widget(top)
        hbody.add_widget(
            MDLabel(
                text=f"{supplier.upper()} · {description.upper()}",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
            )
        )
        hbody.add_widget(
            MDLabel(
                text=sales_date,
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
            )
        )
        hbody.add_widget(
            MDLabel(
                text=stock_mode,
                bold=True,
                theme_text_color="Custom",
                text_color=_AP_ACCENT,
                font_style="Caption",
                size_hint_y=None,
                height=dp(20),
            )
        )
        inv = str(expense.get("invoice_number") or "—")
        pay = str(expense.get("payment_type") or "—")
        hbody.add_widget(
            MDLabel(
                text=f"Invoice {inv} · {pay} · {_inr(amount)}",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
            )
        )
        header.add_widget(hbody)
        self.list.add_widget(header)

        self.list.add_widget(
            MDLabel(
                text=f"LINE ITEMS · {len(lines)}" if lines else "LINE ITEMS",
                bold=True,
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(22),
            )
        )

        if error:
            self.list.add_widget(
                MDLabel(
                    text=error,
                    theme_text_color="Custom",
                    text_color=theme.WARN,
                    size_hint_y=None,
                    height=dp(36),
                )
            )

        if not lines:
            self.list.add_widget(
                MDLabel(
                    text=(
                        "No stock-in products linked to this purchase.\n"
                        "Ledger entries without a stock-in show header only."
                    ),
                    halign="center",
                    theme_text_color="Custom",
                    text_color=theme.TEXT_MUTED,
                    size_hint_y=None,
                    height=dp(56),
                )
            )
        else:
            for line in lines:
                if isinstance(line, dict):
                    self._add_line_card(line)

        self.list.add_widget(
            MDRaisedButton(
                text="Approve",
                md_bg_color=theme.SUCCESS_SOFT,
                theme_text_color="Custom",
                text_color=theme.SUCCESS,
                size_hint_y=None,
                height=dp(48),
                on_release=lambda *_a, r=fallback: self._approve_one(r),
            )
        )

    def _add_line_card(self, line: dict) -> None:
        card = MDCard(
            orientation="horizontal",
            size_hint_y=None,
            height=dp(72),
            padding=0,
            radius=[dp(20)],
            md_bg_color=theme.SURFACE,
            elevation=0,
            line_color=_CARD_LINE,
            line_width=1,
        )
        card.add_widget(self._make_accent_bar(theme.SUCCESS))
        body = MDBoxLayout(orientation="vertical", padding=[dp(12), dp(10), dp(12), dp(10)], spacing=dp(2))
        top = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(22))
        top.add_widget(
            MDLabel(
                text=str(line.get("item_name") or "—"),
                bold=True,
                theme_text_color="Custom",
                text_color=theme.TEXT,
            )
        )
        top.add_widget(
            MDLabel(
                text=_inr(float(line.get("amount") or 0)),
                bold=True,
                halign="right",
                theme_text_color="Custom",
                text_color=_AP_ACCENT,
            )
        )
        body.add_widget(top)
        qty = line.get("qty")
        unit = str(line.get("unit") or "").strip()
        qty_s = f"{qty} {unit}".strip() if qty is not None else "—"
        rate = line.get("unit_cost")
        meta = qty_s if rate is None else f"{qty_s} · @ {_inr(float(rate))}"
        body.add_widget(
            MDLabel(
                text=meta.upper(),
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                font_style="Caption",
                size_hint_y=None,
                height=dp(18),
            )
        )
        card.add_widget(body)
        self.list.add_widget(card)

    def _show_outstanding(self, *, silent: bool = False) -> None:
        if self._detail_open and not silent:
            self._close_detail(refresh=False)
        self._mode = "outstanding"
        self._set_mode_buttons("outstanding")
        if not silent:
            self.status.text = "Loading pending approvals…"

        def work():
            return approvals_api.fetch_outstanding(self.app.api)

        def ok(rows: list[OutstandingExpense]):
            if self._mode != "outstanding" or self._detail_open:
                return
            fp = "pending|" + "|".join(f"{r.id}:{r.balance}" for r in rows)
            if silent and fp == self._fingerprint:
                self._pending_count = len(rows)
                self._set_mode_buttons("outstanding")
                return
            self._fingerprint = fp
            self._outstanding = rows
            self._pending_count = len(rows)
            self._set_mode_buttons("outstanding")
            self.list.clear_widgets()
            self.status.text = f"{len(rows)} pending"
            for row in rows:
                self._add_pending_card(row)
            if rows:
                self.list.add_widget(
                    MDLabel(
                        text="— That's all for now —\nYou've reached the end of the list",
                        halign="center",
                        theme_text_color="Custom",
                        text_color=theme.TEXT_MUTED,
                        size_hint_y=None,
                        height=dp(48),
                    )
                )

        def err(exc):
            if self._mode != "outstanding" or silent or self._detail_open:
                return
            self.status.text = str(exc)
            toast(str(exc))

        run_async(work, ok, err)

    def _show_history(self, *, silent: bool = False) -> None:
        if self._detail_open and not silent:
            self._close_detail(refresh=False)
        self._mode = "history"
        self._set_mode_buttons("history")
        if not silent:
            self.status.text = "Loading approved…"

        def work():
            return approvals_api.fetch_history(self.app.api)

        def ok(rows):
            if self._mode != "history" or self._detail_open:
                return
            fp = "approved|" + "|".join(f"{r.id}:{r.total_amount}" for r in rows)
            if silent and fp == self._fingerprint:
                self._approved_count = len(rows)
                self._set_mode_buttons("history")
                return
            self._fingerprint = fp
            self._approved_count = len(rows)
            self._set_mode_buttons("history")
            self.list.clear_widgets()
            self.status.text = f"{len(rows)} approved"
            for row in rows:
                self._add_history_card(row)
            if rows:
                self.list.add_widget(
                    MDLabel(
                        text="— That's all for now —\nYou've reached the end of the list",
                        halign="center",
                        theme_text_color="Custom",
                        text_color=theme.TEXT_MUTED,
                        size_hint_y=None,
                        height=dp(48),
                    )
                )

        def err(exc):
            if self._mode != "history" or silent or self._detail_open:
                return
            self.status.text = str(exc)
            toast(str(exc))

        run_async(work, ok, err)

    def _approve_one(self, row: OutstandingExpense) -> None:
        if not row.supplier_id:
            toast("Missing supplier on expense")
            return
        self._busy = True

        def work():
            return approvals_api.create_verification(
                self.app.api,
                supplier_id=row.supplier_id,
                allocations=[{"expense_id": row.id, "amount": row.balance}],
            )

        def ok(_data):
            self._busy = False
            self._fingerprint = ""
            toast("Verified")
            self._detail_open = False
            self._detail_expense = None
            self._set_list_chrome_visible(True)
            self._show_outstanding()

        def err(exc):
            self._busy = False
            toast(str(exc))

        run_async(work, ok, err)

    def _revert(self, payment_id: int) -> None:
        self._busy = True

        def work():
            approvals_api.delete_verification(self.app.api, payment_id)
            return True

        def ok(_):
            self._busy = False
            self._fingerprint = ""
            toast("Reverted")
            self._show_history()

        def err(exc):
            self._busy = False
            toast(str(exc))

        run_async(work, ok, err)
