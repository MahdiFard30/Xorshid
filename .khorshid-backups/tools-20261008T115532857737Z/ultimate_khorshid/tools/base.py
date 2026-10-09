"""Tool base — BaseTool / ToolSpec / ToolExecutor (الگو از OpenJarvis)."""

from __future__ import annotations

import concurrent.futures
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from ultimate_khorshid.core.events import EventBus
from ultimate_khorshid.core.types import ToolCall, ToolResult


@dataclass(slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    category: str = "general"
    requires_confirmation: bool = False
    timeout_seconds: float = 30.0
    required_capabilities: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseTool(ABC):
    tool_id: str = ""
    is_local: bool = True

    @property
    @abstractmethod
    def spec(self) -> ToolSpec: ...

    @abstractmethod
    def execute(self, **params: Any) -> ToolResult: ...

    def to_openai_function(self) -> Dict[str, Any]:
        s = self.spec
        return {"type": "function", "function": {
            "name": s.name, "description": s.description, "parameters": s.parameters}}


class ToolExecutor:
    """اجرای ابزارها با تایم‌اوت، تأییدیه، ایونت و rate-limit ساده."""

    def __init__(self, tools: List[BaseTool], bus: Optional[EventBus] = None, *,
                 interactive: bool = False,
                 confirm_callback: Optional[Callable[[str], bool]] = None,
                 default_timeout: float = 60.0,
                 max_retries: int = 1, retry_on_failure: bool = False,
                 fallbacks: Optional[Dict[str, str]] = None) -> None:
        self._tools: Dict[str, BaseTool] = {t.spec.name: t for t in tools}
        self._bus = bus
        self._interactive = interactive
        self._confirm = confirm_callback
        self._default_timeout = default_timeout
        self._max_retries = max(0, max_retries)
        self._retry_on_failure = retry_on_failure
        self._fallbacks = dict(fallbacks or {})
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="khorshid-tool")

    @property
    def tools(self) -> Dict[str, BaseTool]:
        return self._tools

    def openai_tools(self) -> List[Dict[str, Any]]:
        return [t.to_openai_function() for t in self._tools.values()]

    def execute(self, call: ToolCall, _fb_depth: int = 0) -> ToolResult:
        from ultimate_khorshid.core.control import check_cancelled
        check_cancelled()  # لغو توسط کاربر → CancelledError
        tool = self._tools.get(call.name)
        if tool is None:
            fb = self._fallbacks.get(call.name)
            if fb and _fb_depth < 2:
                return self.execute(ToolCall(name=fb, arguments=call.arguments,
                                             id=call.id), _fb_depth + 1)
            return ToolResult(tool_name=call.name, content=f"ابزار ناشناخته: {call.name}", success=False)
        try:
            params = json.loads(call.arguments) if call.arguments else {}
        except json.JSONDecodeError:
            try:  # تعمیر JSON خراب LLM به‌جای خطای خشک
                from ultimate_khorshid.core.jsonx import parse_loose
                params = parse_loose(call.arguments or "{}")
            except Exception as e:
                return ToolResult(tool_name=call.name, content=f"آرگومان JSON نامعتبر: {e}", success=False)
        if not isinstance(params, dict):
            return ToolResult(tool_name=call.name, content="آرگومان باید آبجکت JSON باشد.", success=False)

        # تأییدیه برای ابزارهای خطرناک
        if tool.spec.requires_confirmation and self._interactive:
            ok = self._ask_confirm(tool.spec.name, params)
            if not ok:
                if self._bus:
                    self._bus.publish("security_deny", tool=tool.spec.name)
                return ToolResult(tool_name=call.name, content="کاربر اجازه نداد (denied).", success=False,
                                  metadata={"denied": True})

        if self._bus:
            self._bus.publish("tool_call_start", tool=call.name, params=params)
        from ultimate_khorshid.core.tracing import traced_span
        t0 = time.time()
        timeout = tool.spec.timeout_seconds or self._default_timeout
        attempts = 0
        res: ToolResult
        with traced_span(f"tool.{call.name}", kind="tool",
                         attrs={"args": json.dumps(params, ensure_ascii=False)[:400]}):
            while True:
                attempts += 1
                fut = self._pool.submit(_safe_run, tool, params)
                try:
                    res = fut.result(timeout=timeout)
                    timed_out = False
                except concurrent.futures.TimeoutError:
                    res = ToolResult(tool_name=call.name,
                                     content=f"تایم‌اوت بعد از {timeout} ثانیه.", success=False)
                    timed_out = True
                except Exception as e:
                    res = ToolResult(tool_name=call.name, content=f"خطای اجرا: {e}", success=False)
                    timed_out = True
                should_retry = attempts <= self._max_retries and (
                    timed_out or (self._retry_on_failure and not res.success))
                if not should_retry:
                    break
                time.sleep(min(0.5 * attempts, 3.0))
        if not res.success and _fb_depth < 2 and call.name in self._fallbacks:
            fb = self._fallbacks[call.name]
            res = self.execute(ToolCall(name=fb, arguments=call.arguments, id=call.id),
                               _fb_depth + 1)
            try:
                res.metadata["fallback_from"] = call.name
            except Exception:
                pass
        res.latency_ms = (time.time() - t0) * 1000
        if self._bus:
            self._bus.publish("tool_call_end", tool=call.name, success=res.success, latency_ms=res.latency_ms)
        return res

    def _ask_confirm(self, name: str, params: Dict[str, Any]) -> bool:
        if self._confirm:
            try:
                return bool(self._confirm(f"اجرای ابزار `{name}` با {json.dumps(params, ensure_ascii=False)[:300]}؟"))
            except Exception:
                return False
        return True

    def shutdown(self) -> None:
        try:
            self._pool.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass


def _safe_run(tool: BaseTool, params: Dict[str, Any]) -> ToolResult:
    try:
        r = tool.execute(**params)
        if not isinstance(r, ToolResult):
            r = ToolResult(tool_name=tool.spec.name, content=str(r), success=True)
        r.tool_name = tool.spec.name
        return r
    except Exception as e:
        return ToolResult(tool_name=tool.spec.name, content=f"خطا: {e}", success=False)
