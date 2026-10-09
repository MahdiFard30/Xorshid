"""InferenceEngine ABC — هر بک‌اند استنتاج این اینترفیس را پیاده می‌کند."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class EngineConnectionError(Exception):
    pass


class InferenceEngine(ABC):
    engine_id: str = "base"
    supports_streaming: bool = False

    @abstractmethod
    def generate(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """خروجی استاندارد: {content, tool_calls:[{name,arguments,id}], finish_reason, usage}"""

    def generate_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        *,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        **kwargs: Any,
    ):
        """پیش‌فرض: تولید یک‌جا + yield تکه‌تکه. موتورهای واقعی override می‌کنند.
        هر chunk: {delta, done, result?}"""
        res = self.generate(messages, model, tools=tools, temperature=temperature,
                            max_tokens=max_tokens, **kwargs)
        text = str(res.get("content", ""))
        for i in range(0, max(len(text), 1), 80):
            yield {"delta": text[i:i + 80], "done": False}
        yield {"delta": "", "done": True, "result": res}

    def health(self) -> Dict[str, Any]:
        return {"engine": self.engine_id, "ok": True}


def messages_to_text(messages: List[Dict[str, Any]]) -> str:
    out = []
    for m in messages:
        out.append(f"[{m.get('role')}]: {m.get('content','')}")
    return "\n".join(out)
