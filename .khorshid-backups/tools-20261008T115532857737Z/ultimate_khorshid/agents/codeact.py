"""CodeActAgent — تولید و اجرای کد پایتون (مثل native_openhands در OpenJarvis)."""

from __future__ import annotations

import re
from typing import List

from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.core.registry import AgentRegistry
from ultimate_khorshid.core.types import ToolCall, ToolResult

CODE_PROMPT = """تو یک ایجنت CodeAct هستی: برای حل مسئله، کد پایتون می‌نویسی و با ابزار python_exec اجرایش می‌کنی.
قوانین:
- کد را داخل ```python ... ``` بگذار و بعد با python_exec اجرا کن (یا مستقیم از orchestrator بخواه).
- بعد از دیدن خروجی/خطا، کد را اصلاح کن و دوباره اجرا کن (حداکثر {max} دور).
- در پایان، پاسخ نهایی فارسی بده.
"""

CODE_RE = re.compile(r"```python\s*(.*?)```", re.S | re.I)


@AgentRegistry.register("codeact")
@AgentRegistry.register("native_openhands")
class CodeActAgent(ToolUsingAgent):
    agent_id = "codeact"

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        messages = self._build_messages(ctx, CODE_PROMPT.format(max=self._max_turns))
        tools = [t.to_openai_function() for t in (self._executor.tools.values() if self._executor else [])]
        results: List[ToolResult] = []
        turns = 0
        for _ in range(self._max_turns):
            turns += 1
            res = self._generate(messages, tools=tools or None)
            content = self._strip_think(res.get("content", "") or "")
            calls = res.get("tool_calls", []) or []
            # اگر مدل tool_call نداد ولی کد پایتون داد → خودمان اجرا می‌کنیم
            if not calls:
                codes = CODE_RE.findall(content)
                if codes and self._executor and "python_exec" in self._executor.tools:
                    import json
                    calls = [{"name": "python_exec",
                              "arguments": json.dumps({"code": codes[-1][:6000]}, ensure_ascii=False),
                              "id": f"codeact{turns}"}]
                else:
                    self._emit("agent_end", turns=turns)
                    return AgentResult(content=content, tool_results=results, turns=turns)
            messages.append({"role": "assistant", "content": content})
            for c in calls:
                tr = self._executor.execute(ToolCall(name=c.get("name", ""),
                                                     arguments=c.get("arguments", "{}"))) if self._executor else ToolResult(
                    tool_name="?", content="executor نیست", success=False)
                results.append(tr)
                messages.append({"role": "tool", "content": f"[{'OK' if tr.success else 'ERR'}] {tr.content[:4000]}",
                                 "name": c.get("name", "")})
        self._emit("agent_end", turns=turns, max_turns_exceeded=True)
        return AgentResult(content="به سقف دورها رسیدم. آخرین نتایج ابزارها در دسترس است.",
                           tool_results=results, turns=turns, metadata={"max_turns_exceeded": True})
