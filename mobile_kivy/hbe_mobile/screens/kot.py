"""Kitchen Order Tokens — resend / edit active KOTs (pre-invoice)."""

from __future__ import annotations

from typing import Any, Optional

from kivy.core.clipboard import Clipboard
from kivy.graphics import Color, Rectangle
from kivy.metrics import dp
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.widget import Widget
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

_REST = "#1877F2"
_REST_PRESS = "#1565C0"
_BAR = "#1877F2"
_BAR_PRESS = "#1565C0"
_CHIP_BORDER = "#E2E8F0"
_CARD_LINE = "#EEF1F4"
_WHITE = "#FFFFFF"


class _TapRow(ButtonBehavior, MDBoxLayout):
    pass


class _GoldRule(Widget):
    """Short 32×2 gold rule under the KOT title (left-aligned)."""

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


class _KotChip(ButtonBehavior, MDCard):
    """32px pill chip — refresh / Resend / Edit."""

    def __init__(self, caption: str, on_press, *, accent: str, **kwargs):
        super().__init__(**kwargs)
        self._on_press = on_press
        self._accent = accent
        self.orientation = "horizontal"
        self.size_hint = (None, None)
        self.height = dp(32)
        self.width = max(dp(72), dp(28) + len(caption) * dp(7.4))
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
        self.set_selected(False)

    def set_selected(self, selected: bool) -> None:
        if selected:
            self.md_bg_color = self._accent
            self.line_color = self._accent
            self._caption.text_color = _WHITE
        else:
            self.md_bg_color = theme.SURFACE
            self.line_color = _CHIP_BORDER
            self._caption.text_color = theme.TEXT

    def on_release(self):
        if self._on_press:
            self._on_press()


class _KotAction(ButtonBehavior, MDCard):
    """40px pill primary / ghost action for token cards."""

    def __init__(self, caption: str, on_press, *, accent: str, primary: bool = True, **kwargs):
        super().__init__(**kwargs)
        self._on_press = on_press
        self.orientation = "horizontal"
        self.size_hint_y = None
        self.height = dp(40)
        self.padding = [dp(12), 0, dp(12), 0]
        self.radius = [dp(20)]
        self.elevation = 0
        self.line_width = 1
        if primary:
            self.md_bg_color = accent
            self.line_color = accent
            fg = _WHITE
        else:
            self.md_bg_color = theme.SURFACE
            self.line_color = accent
            fg = accent
        self.add_widget(
            MDLabel(
                text=caption,
                halign="center",
                valign="middle",
                theme_text_color="Custom",
                text_color=fg,
                bold=True,
                font_style="Body2",
            )
        )

    def on_release(self):
        if self._on_press:
            self._on_press()


class _QtyBtn(ButtonBehavior, MDCard):
    def __init__(self, caption: str, on_press, *, accent: str, disabled: bool = False, **kwargs):
        super().__init__(**kwargs)
        self._on_press = None if disabled else on_press
        self.size_hint = (None, None)
        self.size = (dp(28), dp(28))
        self.radius = [dp(10)]
        self.elevation = 0
        self.line_width = 1
        self.md_bg_color = theme.SURFACE
        self.line_color = accent
        self.opacity = 0.4 if disabled else 1
        self.add_widget(
            MDLabel(
                text=caption,
                halign="center",
                valign="middle",
                theme_text_color="Custom",
                text_color=accent,
                bold=True,
            )
        )

    def on_release(self):
        if self._on_press:
            self._on_press()


class KotScreen(MDScreen):
    def __init__(self, app, *, api_base: str = "/point-of-sale", **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "kot"
        self.md_bg_color = theme.BG
        self.pos_api = PosApi(app.api, base=api_base)
        self._is_bar = "bar" in (api_base or "").lower()
        self._accent = _BAR if self._is_bar else _REST
        self._accent_press = _BAR_PRESS if self._is_bar else _REST_PRESS
        self._mode = "resend"
        self._tables: list[dict[str, Any]] = []
        self._expanded: set[int] = set()
        self._draft_qty: dict[str, float] = {}
        self._selected: set[str] = set()
        self._dialog: Optional[MDDialog] = None
        self._reason_field: Optional[MDTextField] = None
        self._pending_changes: list[dict[str, Any]] = []

        root = MDBoxLayout(
            orientation="vertical",
            padding=[dp(20), dp(12), dp(20), dp(16)],
            spacing=dp(8),
        )

        head = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(8))
        head.add_widget(
            MDLabel(
                text="Bar KOT" if self._is_bar else "Restaurant KOT",
                bold=True,
                font_style="H5",
                theme_text_color="Custom",
                text_color=theme.TEXT,
                size_hint_y=None,
                height=dp(36),
            )
        )
        self.btn_refresh = _KotChip("Refresh", lambda: self._load(), accent=self._accent)
        head.add_widget(self.btn_refresh)
        root.add_widget(head)
        root.add_widget(_GoldRule())

        self.status = MDLabel(
            text="Active KOTs until invoice generation.",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            font_style="Caption",
            size_hint_y=None,
            height=dp(18),
        )
        root.add_widget(self.status)

        tabs = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(36), spacing=dp(8))
        self.btn_resend = _KotChip("Resend", lambda: self._set_mode("resend"), accent=self._accent)
        self.btn_edit = _KotChip("Edit", lambda: self._set_mode("edit"), accent=self._accent)
        self.btn_resend.set_selected(True)
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
        self.btn_resend.set_selected(self._mode == "resend")
        self.btn_edit.set_selected(self._mode == "edit")
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
            empty = MDCard(
                orientation="vertical",
                padding=dp(20),
                size_hint_y=None,
                height=dp(96),
                radius=[dp(20)],
                md_bg_color=theme.SURFACE,
                elevation=0,
                line_color=_CARD_LINE,
                line_width=1,
            )
            empty.add_widget(
                MDLabel(
                    text=(
                        "No active KOTs. Tokens appear after Send KOT "
                        "and clear after Generate Invoice."
                    ),
                    theme_text_color="Custom",
                    text_color=theme.TEXT_MUTED,
                    halign="center",
                    size_hint_y=None,
                    height=dp(56),
                )
            )
            self.list_box.add_widget(empty)
            return

        for idx, token in enumerate(self._tables):
            card = MDCard(
                orientation="vertical",
                padding=dp(16),
                spacing=dp(8),
                size_hint_y=None,
                radius=[dp(20)],
                md_bg_color=theme.SURFACE,
                elevation=0,
                line_color=_CARD_LINE,
                line_width=1,
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
                height=dp(42),
                spacing=dp(2),
            )
            head.add_widget(
                MDLabel(
                    text=str(token.get("name") or "Table"),
                    bold=True,
                    theme_text_color="Custom",
                    text_color=theme.TEXT,
                    font_style="Body1",
                    size_hint_y=None,
                    height=dp(22),
                )
            )
            head.add_widget(
                MDLabel(
                    text=meta,
                    theme_text_color="Custom",
                    text_color=theme.TEXT_MUTED,
                    font_style="Caption",
                    size_hint_y=None,
                    height=dp(16),
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
                    height=dp(88) if self._mode == "resend" else dp(40),
                    spacing=dp(8),
                )
                if self._mode == "resend":
                    actions.add_widget(
                        _KotAction(
                            "Resend selected",
                            lambda i=idx: self._resend(i, selected_only=True),
                            accent=self._accent,
                            primary=True,
                        )
                    )
                    actions.add_widget(
                        _KotAction(
                            "Resend all",
                            lambda i=idx: self._resend(i, selected_only=False),
                            accent=self._accent,
                            primary=False,
                        )
                    )
                else:
                    actions.add_widget(
                        _KotAction(
                            "Save changes",
                            lambda i=idx: self._save_edits(i),
                            accent=self._accent,
                            primary=True,
                        )
                    )
                card.add_widget(actions)

            # Approximate height so scroll layout works before bind settles.
            base = dp(74)
            if open_:
                base += dp(44) * max(1, len(lines)) + (
                    dp(96) if self._mode == "resend" else dp(48)
                )
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

        row = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        if self._mode == "resend":
            selected = key in self._selected
            toggle = MDFlatButton(
                text="✓" if selected else "○",
                theme_text_color="Custom",
                text_color=self._accent if selected else theme.TEXT_MUTED,
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
                _QtyBtn(
                    "−",
                    lambda i=table_idx, ln=line: self._bump_qty(i, ln, -1),
                    accent=self._accent,
                    disabled=qty <= 0,
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
                _QtyBtn(
                    "+",
                    lambda i=table_idx, ln=line: self._bump_qty(i, ln, 1),
                    accent=self._accent,
                    disabled=qty >= 999,
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

    def _queue_kot_reprint(self, token: dict[str, Any], lines: list[dict[str, Any]]) -> None:
        invoice_id = int(token.get("invoice_id") or 0)
        if invoice_id <= 0:
            toast("Missing invoice for print")
            return
        default_outlet = str(self._outlet or "restaurant").lower()
        groups: dict[str, list[dict[str, Any]]] = {}
        for line in lines:
            outlet = str(line.get("outlet") or default_outlet).lower()
            groups.setdefault(outlet, []).append(
                {
                    "name": line.get("name") or "Item",
                    "qty": float(line.get("sent_qty") if line.get("sent_qty") is not None else line.get("qty") or 0),
                    "variant": line.get("variant") or "",
                    "notes": line.get("notes") or "",
                    "outlet": outlet,
                }
            )
        import time

        for idx, (outlet, items) in enumerate(sorted(groups.items())):
            job_id = f"kot-kivy-resend-{outlet}-{invoice_id}-{int(time.time() * 1000)}-{idx}"
            self.pos_api.queue_print_job(
                {
                    "jobId": job_id,
                    "idempotencyKey": job_id,
                    "documentType": "kot",
                    "documentId": invoice_id,
                    "locationId": outlet,
                    "resend": True,
                    "items": items,
                }
            )
        toast("Sent to kitchen printer")

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
        try:
            self._queue_kot_reprint(token, lines)
        except Exception as exc:
            toast(str(exc) or "Could not queue kitchen print")
        return

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
                    md_bg_color=self._accent,
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
