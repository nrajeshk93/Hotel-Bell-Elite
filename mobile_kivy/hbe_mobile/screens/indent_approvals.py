"""Indent Approval — approve or reject pending stores indents."""

from __future__ import annotations

from kivy.metrics import dp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.card import MDCard
from kivymd.uix.dialog import MDDialog
from kivymd.uix.label import MDLabel
from kivymd.uix.screen import MDScreen
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField
from kivymd.toast import toast

from hbe_mobile import theme
from hbe_mobile.api import indent_approvals as indent_api
from hbe_mobile.utils.async_jobs import run_async


class IndentApprovalsScreen(MDScreen):
    def __init__(self, app, **kwargs):
        super().__init__(**kwargs)
        self.app = app
        self.name = "indent_approvals"
        self.md_bg_color = theme.BG
        self._view = "pending"
        self._busy = False
        self._reject_dialog = None
        self._reject_field = None

        root = MDBoxLayout(
            orientation="vertical",
            padding=[dp(14), dp(12), dp(14), dp(8)],
            spacing=dp(10),
        )
        root.add_widget(
            MDLabel(
                text="Indent Approval",
                font_style="H4",
                bold=True,
                theme_text_color="Custom",
                text_color=theme.TEXT,
                size_hint_y=None,
                height=dp(36),
            )
        )

        tabs = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(44), spacing=dp(8))
        self.btn_pending = MDRaisedButton(
            text="Waiting",
            md_bg_color=theme.ACCENT,
            on_release=lambda *_: self._set_view("pending"),
        )
        self.btn_recent = MDFlatButton(
            text="Recent",
            theme_text_color="Custom",
            text_color=theme.ACCENT,
            on_release=lambda *_: self._set_view("recent"),
        )
        tabs.add_widget(self.btn_pending)
        tabs.add_widget(self.btn_recent)
        root.add_widget(tabs)

        self.status = MDLabel(
            text="Loading…",
            theme_text_color="Custom",
            text_color=theme.TEXT_MUTED,
            size_hint_y=None,
            height=dp(24),
        )
        root.add_widget(self.status)

        scroll = MDScrollView()
        self.list_box = MDBoxLayout(
            orientation="vertical",
            spacing=dp(10),
            size_hint_y=None,
            padding=(0, 0, 0, dp(24)),
        )
        self.list_box.bind(minimum_height=self.list_box.setter("height"))
        scroll.add_widget(self.list_box)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_workspace_enter(self) -> None:
        self.refresh()

    def _set_view(self, view: str) -> None:
        self._view = "recent" if view == "recent" else "pending"
        if self._view == "pending":
            self.btn_pending.md_bg_color = theme.ACCENT
            self.btn_recent.md_bg_color = (0, 0, 0, 0)
        else:
            self.btn_recent.md_bg_color = theme.ACCENT
            self.btn_pending.md_bg_color = (0, 0, 0, 0)
        self.refresh()

    def refresh(self) -> None:
        if self._busy:
            return
        self._busy = True
        self.status.text = "Loading…"

        def work():
            return indent_api.list_indents(self.app.api, view=self._view)

        def ok(data):
            self._busy = False
            rows = (data or {}).get("rows") or []
            total = int((data or {}).get("total") or len(rows))
            if self._view == "recent":
                self.status.text = f"{total} recent decision{'s' if total != 1 else ''}"
            else:
                self.status.text = f"{total} waiting"
            self._render(rows)

        def err(exc):
            self._busy = False
            self.status.text = str(getattr(exc, "message", None) or exc)
            self.list_box.clear_widgets()

        run_async(work, on_success=ok, on_error=err)

    def _render(self, rows: list) -> None:
        self.list_box.clear_widgets()
        if not rows:
            self.list_box.add_widget(
                MDLabel(
                    text="Nothing waiting" if self._view == "pending" else "No recent decisions",
                    theme_text_color="Secondary",
                    size_hint_y=None,
                    height=dp(40),
                )
            )
            return
        for row in rows:
            self.list_box.add_widget(self._card(row))

    def _card(self, row: dict) -> MDCard:
        card = MDCard(
            orientation="vertical",
            padding=dp(12),
            spacing=dp(6),
            size_hint_y=None,
            height=dp(168 if self._view == "pending" else 130),
            radius=[12, 12, 12, 12],
            md_bg_color=theme.SURFACE,
        )
        code = str(row.get("indent_no") or f"#{row.get('id')}")
        total = float(row.get("approximate_total") or 0)
        amount = f"₹{total:,.2f}" if total > 0 else "—"
        from_name = str(row.get("created_by_name") or "—")
        outlet = str(row.get("outlet") or "").title()
        items = int(row.get("line_count") or 0)
        card.add_widget(
            MDLabel(
                text=f"{code}  ·  {amount}",
                bold=True,
                theme_text_color="Custom",
                text_color=theme.TEXT,
                size_hint_y=None,
                height=dp(24),
            )
        )
        card.add_widget(
            MDLabel(
                text=f"{from_name} · {outlet} · {items} item{'s' if items != 1 else ''}",
                theme_text_color="Custom",
                text_color=theme.TEXT_MUTED,
                size_hint_y=None,
                height=dp(20),
            )
        )
        notes = str(row.get("notes") or "").strip()
        if notes:
            card.add_widget(
                MDLabel(
                    text=notes[:120],
                    theme_text_color="Secondary",
                    size_hint_y=None,
                    height=dp(20),
                )
            )
        if self._view == "recent":
            status = str(row.get("status") or "")
            by = str(row.get("decided_by_name") or "—")
            card.add_widget(
                MDLabel(
                    text=f"{status.title()} · by {by}",
                    theme_text_color="Custom",
                    text_color=theme.ACCENT if status == "approved" else theme.TEXT_MUTED,
                    size_hint_y=None,
                    height=dp(22),
                )
            )
            return card

        actions = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(8))
        indent_id = int(row.get("id") or 0)
        outlet_key = str(row.get("outlet") or "bar")
        actions.add_widget(
            MDRaisedButton(
                text="Approve",
                md_bg_color=theme.SUCCESS,
                on_release=lambda *_a, i=indent_id, o=outlet_key: self._approve(i, o),
            )
        )
        actions.add_widget(
            MDRaisedButton(
                text="Reject",
                md_bg_color=theme.DANGER,
                on_release=lambda *_a, i=indent_id, o=outlet_key, n=code: self._open_reject(i, o, n),
            )
        )
        card.add_widget(actions)
        return card

    def _approve(self, indent_id: int, outlet: str) -> None:
        if self._busy:
            return
        self._busy = True
        self.status.text = "Approving…"

        def work():
            indent_api.decide_indent(
                self.app.api,
                indent_id=indent_id,
                decision="approved",
                outlet=outlet,
            )

        def ok(_):
            self._busy = False
            toast("Indent approved")
            self.refresh()

        def err(exc):
            self._busy = False
            self.status.text = str(getattr(exc, "message", None) or exc)
            toast(self.status.text)

        run_async(work, on_success=ok, on_error=err)

    def _open_reject(self, indent_id: int, outlet: str, indent_no: str) -> None:
        self._reject_field = MDTextField(
            hint_text="Reason for rejection",
            helper_text="Required",
            helper_text_mode="on_error",
            maxlength=200,
        )
        self._reject_dialog = MDDialog(
            title=f"Reject {indent_no}",
            type="custom",
            content_cls=self._reject_field,
            buttons=[
                MDFlatButton(text="Cancel", on_release=lambda *_: self._reject_dialog.dismiss()),
                MDRaisedButton(
                    text="Reject",
                    md_bg_color=(0.86, 0.15, 0.15, 1),
                    on_release=lambda *_: self._confirm_reject(indent_id, outlet),
                ),
            ],
        )
        self._reject_dialog.open()

    def _confirm_reject(self, indent_id: int, outlet: str) -> None:
        note = (self._reject_field.text or "").strip() if self._reject_field else ""
        if not note:
            if self._reject_field:
                self._reject_field.error = True
            toast("Add a short reason when rejecting")
            return
        if self._reject_dialog:
            self._reject_dialog.dismiss()
        if self._busy:
            return
        self._busy = True
        self.status.text = "Rejecting…"

        def work():
            indent_api.decide_indent(
                self.app.api,
                indent_id=indent_id,
                decision="rejected",
                outlet=outlet,
                decision_note=note,
            )

        def ok(_):
            self._busy = False
            toast("Indent rejected")
            self.refresh()

        def err(exc):
            self._busy = False
            self.status.text = str(getattr(exc, "message", None) or exc)
            toast(self.status.text)

        run_async(work, on_success=ok, on_error=err)
