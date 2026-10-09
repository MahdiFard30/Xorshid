"""Human-in-the-loop — کنترل اجرای زنده: pause / resume / cancel.

Runtime یک RunController می‌سازد و در contextvar می‌گذارد؛
ToolExecutor قبل از هر ابزار check() می‌کند. داشبورد/CLI آینده می‌تواند
همین کنترلر را pause/cancel کند.
"""

from __future__ import annotations

import contextvars
import threading
import time
from contextlib import contextmanager
from typing import Callable, Iterator, Optional


class CancelledError(Exception):
    pass


class RunController:
    def __init__(self) -> None:
        self._paused = threading.Event()
        self._cancelled = threading.Event()
        self.notes: list = []

    # -- فرمان‌ها --
    def pause(self, note: str = "") -> None:
        self._paused.set()
        if note:
            self.notes.append(f"paused: {note}")

    def resume(self) -> None:
        self._paused.clear()
        self.notes.append("resumed")

    def cancel(self, note: str = "") -> None:
        self._cancelled.set()
        if note:
            self.notes.append(f"cancelled: {note}")

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    def check(self, poll: float = 0.05, timeout: Optional[float] = None) -> None:
        """اگر cancel شده raise؛ اگر pause است صبر کن تا resume/cancel."""
        if self._cancelled.is_set():
            raise CancelledError("اجرا توسط کاربر لغو شد.")
        if not self._paused.is_set():
            return
        t0 = time.time()
        while self._paused.is_set():
            if self._cancelled.is_set():
                raise CancelledError("اجرا توسط کاربر لغو شد.")
            if timeout is not None and (time.time() - t0) > timeout:
                raise TimeoutError("توقف طولانی شد (pause timeout).")
            time.sleep(poll)


_current: contextvars.ContextVar[Optional[RunController]] = contextvars.ContextVar(
    "khorshid_controller", default=None)


def current_controller() -> Optional[RunController]:
    return _current.get()


@contextmanager
def use_controller(ctrl: RunController) -> Iterator[RunController]:
    tok = _current.set(ctrl)
    try:
        yield ctrl
    finally:
        _current.reset(tok)


def check_cancelled() -> None:
    c = _current.get()
    if c is not None:
        c.check()


ApprovalFn = Callable[[str], bool]
