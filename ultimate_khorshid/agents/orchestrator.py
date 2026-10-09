"""OrchestratorAgent — حلقه function-calling چندنوبتی (بهترین برای مدل‌های tool-aware)."""

from __future__ import annotations

from typing import Any, Dict, List

from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.core.registry import AgentRegistry
from ultimate_khorshid.core.types import ToolCall, ToolResult


@AgentRegistry.register("orchestrator")
class OrchestratorAgent(ToolUsingAgent):
    agent_id = "orchestrator"

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        messages = self._build_messages(ctx)
        tools = self._openai_tools(ctx.tools)
        results: List[ToolResult] = []
        turns = 0

        for _ in range(self._max_turns):
            turns += 1
            self._emit("turn_start", turn=turns)
            res = self._generate(messages, tools=tools or None)
            calls = res.get("tool_calls", []) or []
            content = self._strip_think(res.get("content", "") or "")

            if not calls:
                messages.append({"role": "assistant", "content": content})
                self._emit("turn_end", turn=turns)
                self._emit("agent_end", turns=turns)
                return AgentResult(content=content or "(پاسخ خالی)", tool_results=results,
                                   turns=turns, metadata={"model": self._model})

            messages.append({"role": "assistant", "content": content,
                             "tool_calls": [{"id": c.get("id", f"c{i}"),
                                             "name": c.get("name"),
                                             "arguments": c.get("arguments", "{}"),
                                             **({"thought_signature": c["thought_signature"]}
                                                if c.get("thought_signature") else {})}
                                            for i, c in enumerate(calls)]})
            for c in calls:
                tr = self._executor.execute(ToolCall(name=c.get("name", ""),
                                                     arguments=c.get("arguments", "{}"),
                                                     id=c.get("id", ""))) if self._executor else ToolResult(
                    tool_name=c.get("name", ""), content="executor وصل نیست.", success=False)
                results.append(tr)
                messages.append({"role": "tool", "content": f"[{'OK' if tr.success else 'ERR'}] {tr.content[:4000]}",
                                 "tool_call_id": c.get("id", ""), "name": c.get("name", "")})
            self._emit("turn_end", turn=turns, tool_calls=len(calls))

        self._emit("agent_end", turns=turns, max_turns_exceeded=True)
        # جمع‌بندی نهایی
        try:
            fin = self._generate(messages + [{"role": "user", "content": "با توجه به نتایج ابزارها، پاسخ نهایی فارسی و خلاصه بده."}])
            content = self._strip_think(fin.get("content", ""))
        except Exception:
            content = "به سقف گام‌ها رسیدم."
        return AgentResult(content=content, tool_results=results, turns=turns,
                           metadata={"max_turns_exceeded": True})

    def _openai_tools(self, wanted: List[str]) -> List[Dict[str, Any]]:
        if self._executor is None:
            return []
        out = []
        for n, t in self._executor.tools.items():
            if wanted and n not in wanted:
                continue
            out.append(t.to_openai_function())
        return out
