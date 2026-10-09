"""BaseAgent — کلاس پایه همه ایجنت‌ها (الگو از OpenJarvis)."""

from __future__ import annotations

import contextvars
import re
import time
from contextlib import contextmanager
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ultimate_khorshid.core.events import EventBus
from ultimate_khorshid.core.types import Conversation, ToolResult


_stream_sink: contextvars.ContextVar = contextvars.ContextVar(
    "khorshid_stream_sink", default=None)


@contextmanager
def stream_sink_ctx(fn):
    """اگر fn داده شد، توکن‌های همه _generateها به آن پخش می‌شود."""
    tok = _stream_sink.set(fn)
    try:
        yield
    finally:
        _stream_sink.reset(tok)


@dataclass(slots=True)
class AgentContext:
    conversation: Conversation = field(default_factory=Conversation)
    tools: List[str] = field(default_factory=list)
    memory_results: List[Any] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentResult:
    content: str
    tool_results: List[ToolResult] = field(default_factory=list)
    turns: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):
    agent_id: str = "base"
    accepts_tools: bool = False

    def __init__(self, engine: Any, model: str, *,
                 bus: Optional[EventBus] = None,
                 temperature: float = 0.7, max_tokens: int = 1024,
                 system_prompt: str = "", max_turns: int = 12) -> None:
        self._engine = engine
        self._model = model
        self._bus = bus
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._system_prompt = system_prompt
        self._max_turns = max_turns

    @abstractmethod
    def run(self, ctx: AgentContext) -> AgentResult:
        ...

    # ---- helpers ----
    def _emit(self, t: str, **d: Any) -> None:
        if self._bus:
            self._bus.publish(t, agent=self.agent_id, **d)

    def _build_messages(self, ctx: AgentContext, extra_system: str = "") -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = []
        sys = self._system_prompt + (("\n" + extra_system) if extra_system else "")
        if ctx.memory_results:
            mem_txt = "\n".join(f"- {getattr(h, 'text', str(h))[:300]}" for h in ctx.memory_results[:5])
            sys += f"\n\n[حافظه مرتبط]\n{mem_txt}"
        if sys.strip():
            msgs.append({"role": "system", "content": sys})
        for m in ctx.conversation.messages:
            msgs.append(m.to_dict())
        return msgs

    def _generate(self, messages: List[Dict[str, Any]], tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        from ultimate_khorshid.core import context as Ctx
        from ultimate_khorshid.core import cost as Cost
        from ultimate_khorshid.core.tracing import current_trace_id, current_tracer, traced_span
        trimmed, dropped, tok_in = Ctx.trim_messages(
            messages, Ctx.budget_for(self.agent_id), self._model)
        self._emit("generate_start", model=self._model)
        t0 = time.time()
        with traced_span(f"llm.{self.agent_id}", kind="llm",
                         attrs={"model": self._model, "tok_in_est": tok_in,
                                "dropped": dropped}):
            try:
                res = self._generate_inner(trimmed, tools)
            except Exception as e:
                self._emit("error", where="generate", error=str(e)[:300])
                raise
        self._emit("generate_end", latency_ms=(time.time() - t0) * 1000)
        try:
            usage = res.get("usage") or {}
            tin = int(usage.get("input_tokens") or usage.get("prompt_tokens") or tok_in)
            tout = int(usage.get("output_tokens") or usage.get("completion_tokens")
                       or Ctx.estimate_tokens(str(res.get("content", "")), self._model))
            tr, tid = current_tracer(), current_trace_id()
            if tr is not None and tid:
                eng = getattr(self._engine, "engine_id", "?")
                tr.log_usage(tid, eng, self._model, tin, tout,
                             Cost.calc_usd(eng, self._model, tin, tout))
        except Exception:
            pass
        return res

    def _generate_inner(self, messages: List[Dict[str, Any]],
                        tools: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """تولید با استریم اختیاری (اگر sink فعال و موتور ساپورت کند)."""
        sink = _stream_sink.get()
        gen = getattr(self._engine, "generate_stream", None)
        if sink is not None and callable(gen):
            final: Dict[str, Any] = {}
            try:
                for chunk in gen(messages, self._model, tools=tools,
                                 temperature=self._temperature,
                                 max_tokens=self._max_tokens):
                    if isinstance(chunk, dict):
                        if chunk.get("delta"):
                            try:
                                sink(chunk["delta"])
                            except Exception:
                                pass
                        if chunk.get("done"):
                            final = chunk.get("result") or final
                    elif chunk:
                        try:
                            sink(str(chunk))
                        except Exception:
                            pass
            except Exception:
                final = {}
            if final:
                return final
        return self._engine.generate(messages, self._model, tools=tools,
                                     temperature=self._temperature,
                                     max_tokens=self._max_tokens)

    def _generate_stream(self, messages: List[Dict[str, Any]],
                         tools: Optional[List[Dict[str, Any]]] = None,
                         on_token: Any = None) -> Dict[str, Any]:
        """استریم توکن‌ها؛ on_token(delta) برای هر تکه صدا زده می‌شود."""
        from ultimate_khorshid.core import context as Ctx
        trimmed, _, _ = Ctx.trim_messages(
            messages, Ctx.budget_for(self.agent_id), self._model)
        gen = self._engine.generate_stream(
            trimmed, self._model, tools=tools, temperature=self._temperature,
            max_tokens=self._max_tokens)
        if not hasattr(gen, "__iter__"):  # موتور قدیمی بدون استریم
            return self._generate(messages, tools)
        final: Dict[str, Any] = {}
        for chunk in gen:
            d = chunk.get("delta", "") if isinstance(chunk, dict) else str(chunk)
            if d and on_token:
                try:
                    on_token(d)
                except Exception:
                    pass
            if isinstance(chunk, dict) and chunk.get("done"):
                final = chunk.get("result") or final
        return final

    @staticmethod
    def _strip_think(text: str) -> str:
        return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


class ToolUsingAgent(BaseAgent):
    accepts_tools = True

    def __init__(self, *a: Any, executor: Any = None, **kw: Any) -> None:
        super().__init__(*a, **kw)
        self._executor = executor
