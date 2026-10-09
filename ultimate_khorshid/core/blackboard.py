"""Blackboard — حافظه کاری مشترک بین ایجنت‌ها در یک اجرا (multi-agent).

Runtime یک Blackboard در contextvar می‌گذارد؛ ساب‌ایجنت‌ها یافته‌ها را
می‌نویسند و سوپروایزر جمع‌بندی می‌کند.
"""

from __future__ import annotations

import contextvars
import time
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional


class Blackboard:
    def __init__(self) -> None:
        self._notes: Dict[str, Any] = {}
        self._log: List[Dict[str, Any]] = []

    def write(self, key: str, value: Any, author: str = "") -> None:
        self._notes[key] = value
        self._log.append({"key": key, "author": author,
                          "ts": time.strftime("%H:%M:%S")})

    def read(self, key: str, default: Any = None) -> Any:
        return self._notes.get(key, default)

    def all(self) -> Dict[str, Any]:
        return dict(self._notes)

    def summary(self, max_chars: int = 3000) -> str:
        lines = []
        for k, v in self._notes.items():
            s = str(v).replace("\n", " ")
            lines.append(f"• {k}: {s[:300]}")
        out = "\n".join(lines)
        return out[:max_chars]

    def history(self) -> List[Dict[str, Any]]:
        return list(self._log)


_current: contextvars.ContextVar[Optional[Blackboard]] = contextvars.ContextVar(
    "khorshid_blackboard", default=None)


def current_board() -> Optional[Blackboard]:
    return _current.get()


@contextmanager
def use_board(board: Blackboard) -> Iterator[Blackboard]:
    tok = _current.set(board)
    try:
        yield board
    finally:
        _current.reset(tok)
