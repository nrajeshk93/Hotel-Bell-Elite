"""Background work helpers for Kivy main-thread callbacks."""

from __future__ import annotations

import threading
from typing import Callable, Optional

from kivy.clock import Clock


def run_async(work: Callable[[], object], on_success: Callable[[object], None], on_error: Optional[Callable[[BaseException], None]] = None) -> None:
    def _runner() -> None:
        try:
            result = work()
        except BaseException as exc:  # noqa: BLE001 — surface to UI
            if on_error:
                Clock.schedule_once(lambda *_: on_error(exc), 0)
            return
        Clock.schedule_once(lambda *_: on_success(result), 0)

    threading.Thread(target=_runner, daemon=True).start()
