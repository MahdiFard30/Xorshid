"""Core types — پیام‌ها، مکالمه، فراخوانی ابزار، نتایج، مدل‌ها."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
import time
import uuid


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(slots=True)
class Message:
    role: str
    content: str
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            d["name"] = self.name
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        return d


@dataclass(slots=True)
class Conversation:
    messages: List[Message] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def add(self, role: str, content: str, **kw: Any) -> Message:
        m = Message(role=role, content=content, **kw)  # type: ignore[arg-type]
        self.messages.append(m)
        return m

    def to_dicts(self) -> List[Dict[str, Any]]:
        return [m.to_dict() for m in self.messages]


@dataclass(slots=True)
class ToolCall:
    name: str
    arguments: str = "{}"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


@dataclass(slots=True)
class ToolResult:
    tool_name: str
    content: str
    success: bool = True
    latency_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelSpec:
    id: str
    aliases: List[str] = field(default_factory=list)
    engine: str = "mock"
    parameters_b: float = 0.0
    context_window: int = 8192
    supports_tools: bool = False
    local: bool = True
    description: str = ""


@dataclass(slots=True)
class TraceStep:
    kind: str  # route|generate|tool|memory|agent|answer
    detail: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)


@dataclass(slots=True)
class Trace:
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    query: str = ""
    agent: str = ""
    model: str = ""
    steps: List[TraceStep] = field(default_factory=list)
    success: bool = True
    total_ms: float = 0.0
    ts: float = field(default_factory=time.time)

    def add(self, kind: str, detail: str = "", **data: Any) -> None:
        self.steps.append(TraceStep(kind=kind, detail=detail, data=data))
