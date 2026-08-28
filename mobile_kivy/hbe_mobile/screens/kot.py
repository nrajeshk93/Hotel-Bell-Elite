"""Kitchen Order Tokens — resend / edit active KOTs (pre-invoice)."""

from __future__ import annotations

from typing import Any, Optional

from kivy.core.clipboard import Clipboard
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivymd.toast import toast
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from hbe_mobile import theme
from hbe_mobile.api.client import ApiError
from hbe_mobile.api.pos import PosApi, format_kot_slip_text
from hbe_mobile.utils.async_jobs import run_async


class _TapRow(ButtonBehavior, MDBoxLayout):
    pass


class KotScreen(MDScreen):
    def __init__(self, app, *, api_base: str = "/point-of-sale", **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "kot"
        self.md_bg_color = theme.BG
        self.pos_api = PosApi(app.api, base=api_base)
        self._mode = "resend"
        self._tables: list[dict[str, Any]] = []
        self._expanded: set[int] = set()
        self._draft_qty: dict[str, float] = {}
        self._selected: set[str] = set()
        self._dialog: Optional[MDDialog] = None
        self._reason_field: Optional[MDTextField] = None
        self._pending_changes: list[dict[str, Any]] = []

        root = MDBoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))

        head = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(8))
        titles = MDBoxLayout(orientation="vertical", size_hint_x=0.72)
        titles.add_widget(
            MDLabel(
                text="Kitchen Order Tokens",
                bold=True,
                theme_text_color="Custom",
                text_color=theme.LOGIN_NAVY,
                size_hint_y=None,
                height=dp(26),
            )
        )
        self.status = MDLabel(
            text="Active KOTs until invoice generation.",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            font_style="Caption",
            size_hint_y=None,
            height=dp(18),
        )
        titles.add_widget(self.status)
        head.add_widget(titles)
        head.add_widget(
            MDRaisedButton(
                text="Refresh",
                md_bg_color=theme.THEME,
                size_hint_x=0.28,
                on_release=lambda *_: self._load(),
            )
        )
        root.add_widget(head)

        tabs = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8))
        self.btn_resend = MDRaisedButton(
            text="Resend",
            md_bg_color=theme.THEME,
            size_hint_x=0.5,
            on_release=lambda *_: self._set_mode("resend"),
        )
        self.btn_edit = MDFlatButton(
            text="Edit",
            theme_text_color="Custom",
            text_color=theme.THEME,
            size_hint_x=0.5,
            on_release=lambda *_: self._set_mode("edit"),
        )
        tabs.add_widget(self.btn_resend)
        tabs.add_widget(self.btn_edit)
        root.add_widget(tabs)

        scroll = MDScrollView()
        self.list_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            size_hint_y=None,
            padding=(0, 0, 0, dp(16)),
        )
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_workspace_enter(self) -> None:
        self._load()

    def _set_mode(self, mode: str) -> None:
        self._mode = "edit" if mode == "edit" else "resend"
        if self._mode == "resend":
            self.btn_resend.md_bg_color = theme.THEME
            self.btn_resend.theme_text_color = "Custom"
            self.btn_resend.text_color = (1, 1, 1, 1)
            self.btn_edit.md_bg_color = (0, 0, 0, 0)
            self.btn_edit.theme_text_color = "Custom"
            self.btn_edit.text_color = theme.THEME
        else:
            self.btn_edit.md_bg_color = theme.THEME
            self.btn_edit.theme_text_color = "Custom"
            self.btn_edit.text_color = (1, 1, 1, 1)
            self.btn_resend.md_bg_color = (0, 0, 0, 0)
            self.btn_resend.theme_text_color = "Custom"
            self.btn_resend.text_color = theme.THEME
        self._render()

    def _line_key(self, table_idx: int, line_id: Any) -> str:
        return f"{table_idx}:{line_id}"

    def _line_qty(self, table_idx: int, line: dict[str, Any]) -> float:
        key = self._line_key(table_idx, line.get("id"))
        if key in self._draft_qty:
            return float(self._draft_qty[key])
        raw = line.get("sent_qty")
        if raw is None:
            raw = line.get("qty")
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0

    def _orig_qty(self, line: dict[str, Any]) -> float:
        raw = line.get("sent_qty")
        if raw is None:
            raw = line.get("qty")
        try:
            return float(raw or 0)
        except (TypeError, ValueError):
            return 0.0

    def _load(self) -> None:
        self.status.text = "Loading kitchen tokens…"

        def work():
            return self.pos_api.list_kot_tokens()

        def ok(data):
            tables = data.get("tables") if isinstance(data, dict) else None
            self._tables = [t for t in (tables or []) if isinstance(t, dict)]
            self._draft_qty = {}
            self._selected = set()
            count = len(self._tables)
            self.status.text = (
                "No active KOTs"
                if count == 0
                else f"Showing {count} token{'s' if count != 1 else ''}"
            )
            self._render()

        def err(exc):
            self._tables = []
            self._render()
            self.status.text = str(exc)
            toast(str(exc))

        run_async(work, ok, err)

    def _dismiss_dialog(self) -> None:
        if self._dialog:
            try:
                self._dialog.dismiss()
            except Exception:
                pass
            self._dialog = None
        self._reason_field = None
        self._pending_changes = []

    def _render(self) -> None:
        self.list_box.clear_widgets()
        if not self._tables:
            self.list_box.add_widget(
                MDLabel(
                    text=(
                        "No active KOTs. Tokens appear after Send KOT "
                        "and clear after Generate Invoice."
                    ),
                    theme_text_color="Custom",
                    text_color=theme.TEXT_MUTED,
                    halign="center",
                    size_hint_y=None,
                    height=dp(72),
                )
            )
            return

        for idx, token in enumerate(self._tables):
            card = MDCard(
                orientation="vertical",
                padding=dp(12),
                spacing=dp(8),
                size_hint_y=None,
                radius=[dp(14)],
                md_bg_color=theme.SURFACE,
                elevation=1,
            )
            card.bind(minimum_height=card.setter("height"))

            kot_no = token.get("kot_no") or token.get("order_no") or "—"
            lines = [ln for ln in (token.get("lines") or []) if isinstance(ln, dict)]
            items = int(token.get("sent_items") or len(lines) or 0)
            sent_at = str(token.get("sent_at") or "").strip()
            meta = f"{kot_no} · {items} item{'s' if items != 1 else ''}"
            if sent_at:
                meta = f"{meta} · {sent_at}"

            open_ = idx in self._expanded
            head = _TapRow(
                orientation="vertical",
                size_hint_y=None,
                height=dp(48),
                spacing=dp(2),
            )
            head.add_widget(
                MDLabel(
                    text=str(token.get("name") or "Table"),
                    bold=True,
                    theme_text_color="Custom",
                    text_color=theme.LOGIN_NAVY,
                    size_hint_y=None,
                    height=dp(24),
                )
            )
            head.add_widget(
                MDLabel(
                    text=meta,
                    theme_text_color="Custom",
                    text_color=theme.TEXT_MUTED,
                    font_style="Caption",
                    size_hint_y=None,
                    height=dp(18),
                )
            )
            head.bind(on_release=lambda *_a, i=idx: self._toggle(i))
            card.add_widget(head)

            if open_:
                for line in lines:
                    card.add_widget(self._build_line_row(idx, line))
                actions = MDBoxLayout(
                    orientation="vertical",
                    size_hint_y=None,
                    height=dp(96) if self._mode == "resend" else dp(48),
                    spacing=dp(6),
                )
                if self._mode == "resend":
                    actions.add_widget(
                        MDRaisedButton(
                            text="Resend selected",
                            md_bg_color=theme.THEME,
                            size_hint_x=1,
                            on_release=lambda *_a, i=idx: self._resend(i, selected_only=True),
                        )
                    )
                    actions.add_widget(
                        MDFlatButton(
                            text="Resend all",
                            theme_text_color="Custom",
                            text_color=theme.THEME,
                            size_hint_x=1,
                            on_release=lambda *_a, i=idx: self._resend(i, selected_only=False),
                        )
                    )
                else:
                    actions.add_widget(
                        MDRaisedButton(
                            text="Save changes",
                            md_bg_color=theme.THEME,
                            size_hint_x=1,
                            on_release=lambda *_a, i=idx: self._save_edits(i),
                        )
                    )
                card.add_widget(actions)

            # Approximate height so scroll layout works before bind settles.
            base = dp(64)
            if open_:
                base += dp(52) * max(1, len(lines)) + (dp(100) if self._mode == "resend" else dp(56))
            card.height = base
            self.list_box.add_widget(card)

    def _build_line_row(self, table_idx: int, line: dict[str, Any]) -> MDBoxLayout:
        line_id = line.get("id")
        key = self._line_key(table_idx, line_id)
        qty = self._line_qty(table_idx, line)
        orig = self._orig_qty(line)
        name = str(line.get("name") or "Item")
        variant = str(line.get("variant") or "").strip()
        label = f"{name} ({variant})" if variant else name
        notes = str(line.get("notes") or "").strip()

        row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(6))
        if self._mode == "resend":
            selected = key in self._selected
            toggle = MDFlatButton(
                text="✓" if selected else "○",
                theme_text_color="Custom",
                text_color=theme.THEME if selected else theme.TEXT_MUTED,
                size_hint_x=None,
                width=dp(40),
                on_release=lambda *_a, k=key: self._toggle_select(k),
            )
            row.add_widget(toggle)
            row.add_widget(
                MDLabel(
                    text=f"{label} × {orig:g}" + (f"\n{notes}" if notes else ""),
                    theme_text_color="Custom",
                    text_color=theme.TEXT,
                    size_hint_x=1,
                )
            )
        else:
            row.add_widget(
                MDLabel(
                    text=label + (f"\n{notes}" if notes else ""),
                    theme_text_color="Custom",
                    text_color=theme.TEXT,
                    size_hint_x=0.55,
                )
            )
            steppers = MDBoxLayout(orientation="horizontal", size_hint_x=0.45, spacing=dp(4))
            steppers.add_widget(
                MDFlatButton(
                    text="−",
                    theme_text_color="Custom",
                    text_color=theme.THEME,
                    size_hint_x=None,
                    width=dp(36),
                    disabled=qty <= 0,
                    on_release=lambda *_a, i=table_idx, ln=line: self._bump_qty(i, ln, -1),
                )
            )
            steppers.add_widget(
                MDLabel(
                    text=f"{qty:g}",
                    bold=True,
                    halign="center",
                    size_hint_x=None,
                    width=dp(32),
                )
            )
            steppers.add_widget(
                MDFlatButton(
                    text="+",
                    theme_text_color="Custom",
                    text_color=theme.THEME,
                    size_hint_x=None,
                    width=dp(36),
                    disabled=qty >= 999,
                    on_release=lambda *_a, i=table_idx, ln=line: self._bump_qty(i, ln, 1),
                )
            )
            row.add_widget(steppers)
        return row

    def _toggle(self, idx: int) -> None:
        if idx in self._expanded:
            self._expanded.discard(idx)
        else:
            self._expanded.add(idx)
            # Seed selection for this table
            token = self._tables[idx] if 0 <= idx < len(self._tables) else None
            for line in (token or {}).get("lines") or []:
                if isinstance(line, dict) and line.get("id") is not None:
                    self._selected.add(self._line_key(idx, line.get("id")))
        self._render()

    def _toggle_select(self, key: str) -> None:
        if key in self._selected:
            self._selected.discard(key)
        else:
            self._selected.add(key)
        self._render()

    def _bump_qty(self, table_idx: int, line: dict[str, Any], delta: int) -> None:
        key = self._line_key(table_idx, line.get("id"))
        qty = self._line_qty(table_idx, line) + delta
        self._draft_qty[key] = max(0.0, min(999.0, qty))
        self._render()

    def _resend(self, table_idx: int, *, selected_only: bool) -> None:
        if table_idx < 0 or table_idx >= len(self._tables):
            return
        token = self._tables[table_idx]
        lines = [ln for ln in (token.get("lines") or []) if isinstance(ln, dict)]
        if selected_only:
            lines = [
                ln
                for ln in lines
                if self._line_key(table_idx, ln.get("id")) in self._selected
            ]
        if not lines:
            toast("Select at least one item to resend")
            return
        text = format_kot_slip_text(token, lines, resend=True)
        self._dismiss_dialog()

        def copy_slip(*_a):
            try:
                Clipboard.copy(text)
                toast("KOT slip copied")
            except Exception:
                toast("Could not copy slip")
            self._dismiss_dialog()

        self._dialog = MDDialog(
            title="KOT slip preview",
            text=text[:1800] + ("…" if len(text) > 1800 else ""),
            buttons=[
                MDFlatButton(text="Close", on_release=lambda *_: self._dismiss_dialog()),
                MDRaisedButton(
                    text="Copy",
                    md_bg_color=theme.THEME,
                    on_release=copy_slip,
                ),
            ],
        )
        self._dialog.open()

    def _save_edits(self, table_idx: int) -> None:
        if table_idx < 0 or table_idx >= len(self._tables):
            return
        token = self._tables[table_idx]
        invoice_id = int(token.get("invoice_id") or 0)
        changes: list[dict[str, Any]] = []
        has_reduce = False
        for line in token.get("lines") or []:
            if not isinstance(line, dict):
                continue
            orig = self._orig_qty(line)
            next_qty = self._line_qty(table_idx, line)
            if abs(next_qty - orig) < 1e-9:
                continue
            if next_qty < orig:
                has_reduce = True
            changes.append(
                {
                    "invoice_id": invoice_id,
                    "line_id": int(line.get("id") or 0),
                    "sent_qty": next_qty,
                }
            )
        if not changes:
            toast("No quantity changes to save")
            return
        if has_reduce:
            self._prompt_reason(changes)
        else:
            self._submit_changes(changes, "")

    def _prompt_reason(self, changes: list[dict[str, Any]]) -> None:
        self._dismiss_dialog()
        self._pending_changes = changes
        self._reason_field = MDTextField(
            hint_text="Reason for reduction",
            multiline=True,
            size_hint_y=None,
            height=dp(72),
        )
        body = MDBoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None, height=dp(100))
        body.add_widget(
            MDLabel(
                text="Required when reducing kitchen-sent quantities.",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                size_hint_y=None,
                height=dp(24),
            )
        )
        body.add_widget(self._reason_field)
        self._dialog = MDDialog(
            title="Reason for reduction",
            type="custom",
            content_cls=body,
            buttons=[
                MDFlatButton(text="Cancel", on_release=lambda *_: self._dismiss_dialog()),
                MDRaisedButton(
                    text="Save",
                    md_bg_color=theme.THEME,
                    on_release=lambda *_: self._confirm_reason(),
                ),
            ],
        )
        self._dialog.open()

    def _confirm_reason(self) -> None:
        reason = (self._reason_field.text if self._reason_field else "") or ""
        reason = reason.strip()
        if not reason:
            toast("Reason is required for reductions")
            return
        changes = list(self._pending_changes)
        self._dismiss_dialog()
        self._submit_changes(changes, reason)

    def _submit_changes(self, changes: list[dict[str, Any]], reason: str) -> None:
        self.status.text = "Saving KOT edits…"

        def work():
            return self.pos_api.reduce_kot_tokens(changes, reason=reason)

        def ok(_data):
            toast("KOT updated")
            self._load()

        def err(exc):
            msg = str(exc)
            if isinstance(exc, ApiError) and exc.status_code == 403:
                msg = "KOT Cancellation permission required to edit."
            self.status.text = msg
            toast(msg)

        run_async(work, ok, err)
