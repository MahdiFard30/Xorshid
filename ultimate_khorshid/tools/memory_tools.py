"""ابزارهای حافظه — memory_store / memory_search (روی SQLiteMemory)."""

from __future__ import annotations

from typing import Any
from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec


def _mem() -> Any:
    from ultimate_khorshid.memory.store import get_memory
    return get_memory()


@ToolRegistry.register("memory_store")
class MemoryStoreTool(BaseTool):
    tool_id = "memory_store"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="memory_store",
            description="ذخیره دائمی یک نکته/حقیقت در حافظه (نام کاربر، علایق، تصمیمات...).",
            parameters={"type": "object", "properties": {
                "text": {"type": "string"}, "source": {"type": "string"}},
                "required": ["text"]},
            category="memory")

    def execute(self, **p: Any) -> ToolResult:
        text = str(p.get("text", "")).strip()
        if not text:
            return ToolResult(tool_name="memory_store", content="متن خالی است.", success=False)
        mid = _mem().add(text[:2000], str(p.get("source", "user") or "user"))
        return ToolResult(tool_name="memory_store", content=f"🧠 ذخیره شد (#{mid}): {text[:200]}")


@ToolRegistry.register("memory_search")
class MemorySearchTool(BaseTool):
    tool_id = "memory_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="memory_search",
            description="جست‌وجو در حافظه دائمی.",
            parameters={"type": "object", "properties": {
                "query": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["query"]},
            category="memory")

    def execute(self, **p: Any) -> ToolResult:
        q = str(p.get("query", "")).strip()
        hits = _mem().search(q, int(p.get("limit", 5) or 5))
        if not hits:
            return ToolResult(tool_name="memory_search", content="چیزی در حافظه پیدا نشد.")
        lines = [f"#{h.id} [{h.created}] ({h.source}): {h.text[:300]}" for h in hits]
        return ToolResult(tool_name="memory_search", content="🧠 یافته‌ها:\n" + "\n".join(lines))
