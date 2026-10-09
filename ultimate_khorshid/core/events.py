"""EventBus — سیستم رویداد pub/sub برای اتصال اجزا (telemetry، لاگ، UI)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List
import threading
import time


class EventType(str, Enum):
    TURN_START = "turn_start"
    TURN_END = "turn_end"
    GENERATE_START = "generate_start"
    GENERATE_END = "generate_end"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_END = "tool_call_end"
    MEMORY_HIT = "memory_hit"
    ROUTE = "route"
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    ERROR = "error"
    SECURITY_DENY = "security_deny"


@dataclass(slots=True)
class Event:
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


Handler = Callable[[Event], None]


class EventBus:
    """Thread-safe synchronous pub/sub bus."""

    def __init__(self) -> None:
        self._handlers: Dict[str, List[Handler]] = {}
        self._lock = threading.Lock()

    def subscribe(self, event_type: str, handler: Handler) -> None:
        with self._lock:
            self._handlers.setdefault(event_type, []).append(handler)

    def publish(self, event_type: str, **data: Any) -> Event:
        ev = Event(type=event_type, data=data)
        with self._lock:
            handlers = list(self._handlers.get(event_type, [])) + list(
                self._handlers.get("*", [])
            )
        for h in handlers:
            try:
                h(ev)
            except Exception:
                pass
        return ev

    def clear(self) -> None:
        with self._lock:
            self._handlers.clear()
