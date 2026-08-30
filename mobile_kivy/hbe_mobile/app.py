"""MDApp entry — wires ApiClient + screens. No Flask imports."""

from __future__ import annotations

from kivy.clock import Clock
from kivy.core.window import Window
from kivy.uix.screenmanager import ScreenManager
from kivymd.app import MDApp
from kivymd.toast import toast

from hbe_mobile import theme
from hbe_mobile.api.client import ApiClient
from hbe_mobile.screens.approvals import ApprovalsScreen
from hbe_mobile.screens.dashboard import DashboardScreen
from hbe_mobile.screens.home import HomeScreen
from hbe_mobile.screens.indent_approvals import IndentApprovalsScreen
from hbe_mobile.screens.indent_request import IndentRequestScreen
from hbe_mobile.screens.kot import KotScreen
from hbe_mobile.screens.login import LoginScreen
from hbe_mobile.screens.pos_invoice import PosInvoiceScreen
from hbe_mobile.screens.payroll_employees import PayrollEmployeesScreen
from hbe_mobile.screens.payroll_attendance import PayrollAttendanceScreen
from hbe_mobile.screens.payroll_credit import PayrollCreditScreen
from hbe_mobile.screens.payroll_tips import PayrollTipsScreen
from hbe_mobile.screens.shell import WorkspaceShell


class HbeMobileApp(MDApp):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.title = "Hotel Bell Elite"
        self.api = ApiClient()
        self.shell = None
        self.root_manager = None
        self.display_name = ""
        self.access: dict = {}

    def build(self):
        self.theme_cls.primary_palette = "Blue"
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_hue = "600"
        Window.clearcolor = theme.BG

        self.root_manager = ScreenManager()
        login = LoginScreen(self)
        self.shell = WorkspaceShell(self)
        self.shell.register_screens(
            {
                "home": HomeScreen(self),
                "dashboard": DashboardScreen(self),
                "indent_request": IndentRequestScreen(self),
                "indent_approvals": IndentApprovalsScreen(self),
                "pos_invoice": PosInvoiceScreen(self),
                "kot": KotScreen(self),
                "pos_bar_invoice": PosInvoiceScreen(
                    self, outlet="bar", api_base="/bar-point-of-sale"
                ),
                "kot_bar": KotScreen(self, api_base="/bar-point-of-sale"),
                "approvals": ApprovalsScreen(self),
                "payroll_employees": PayrollEmployeesScreen(self),
                "payroll_attendance": PayrollAttendanceScreen(self),
                "payroll_credit": PayrollCreditScreen(self),
                "payroll_tips": PayrollTipsScreen(self),
            }
        )
        self.root_manager.add_widget(login)
        self.root_manager.add_widget(self.shell)
        self.root_manager.current = "login"
        return self.root_manager

    def on_start(self):
        # After UI is up — never block build() or login/POS.
        Clock.schedule_once(self._start_ota_updater, 2.0)

    def _start_ota_updater(self, _dt) -> None:
        try:
            from hbe_mobile.updater import start_background_updater

            start_background_updater(self)
        except Exception:
            import logging

            logging.getLogger("hbe.ota").exception("OTA updater failed to start")

    def on_login_success(self, session) -> None:
        if isinstance(session, str):
            username = session
            access = {}
            display_name = session
        else:
            username = str(getattr(session, "username", "") or "")
            access = dict(getattr(session, "access", None) or {})
            display_name = str(
                getattr(session, "display_name", None) or username
            ).strip() or username
        self.display_name = display_name
        self.access = access
        toast(f"Welcome, {display_name}" if display_name else "Welcome")
        if self.shell:
            self.shell.apply_access(access)
        if self.root_manager and self.shell:
            self.root_manager.current = "workspace"
            # Land on Home so the personalized greeting is visible immediately.
            self.shell.navigate("home")
        try:
            from hbe_mobile.updater import request_update_check

            request_update_check(delay_s=1.5)
        except Exception:
            pass

    def on_resume(self):
        try:
            from hbe_mobile.updater import request_update_check

            request_update_check(delay_s=1.0)
        except Exception:
            pass

    def logout(self) -> None:
        self.display_name = ""
        self.access = {}
        try:
            self.api.logout()
        except Exception:
            pass
        if self.shell:
            self.shell.apply_access({})
        toast("Signed out")
        if self.root_manager:
            try:
                login = self.root_manager.get_screen("login")
                if hasattr(login, "clear_fields"):
                    login.clear_fields()
            except Exception:
                pass
            self.root_manager.current = "login"

    def on_stop(self):
        try:
            self.api.close()
        except Exception:
            pass
        return super().on_stop()
