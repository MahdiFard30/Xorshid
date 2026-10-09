"""ReActAgent — حلقه Thought/Action/Observation با پارس متنی (کار با هر مدلی)."""

from __future__ import annotations

import json
import re
from typing import List

from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.core.registry import AgentRegistry
from ultimate_khorshid.core.types import ToolCall, ToolResult

REACT_PROMPT = """تو یک ایجنت ReAct هستی. در هر گام دقیقاً یکی از این دو قالب را تولید کن:

Thought: <تفکر کوتاه فارسی>
Action: <نام ابزار>
Action Input: <JSON معتبر آرگومان‌ها>

یا وقتی پاسخ نهایی آماده است:
Thought: <تفکر>
Final Answer: <پاسخ نهایی فارسی>

قوانین:
- فقط از ابزارهای موجود استفاده کن.
- Action Input حتماً JSON معتبر باشد.
- حداکثر {max_turns} گام.
"""

ACT_RE = re.compile(r"Action\s*:\s*([a-zA-Z0-9_\-]+)", re.I)
INPUT_RE = re.compile(r"Action\s*Input\s*:\s*(\{.*?\})", re.S | re.I)
FINAL_RE = re.compile(r"Final\s*Answer\s*:\s*(.*)", re.S | re.I)


@AgentRegistry.register("react")
@AgentRegistry.register("native_react")
class ReActAgent(ToolUsingAgent):
    agent_id = "react"

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        tool_names = [t for t in (ctx.tools or [])]
        tools_desc = self._describe_tools(tool_names)
        transcript = ""
        tool_results: List[ToolResult] = []
        turns = 0

        for step in range(self._max_turns):
            turns = step + 1
            prompt = (REACT_PROMPT.format(max_turns=self._max_turns)
                      + f"\nابزارها:\n{tools_desc}\n\n"
                      + f"سؤال کاربر: {self._user_text(ctx)}\n\n{transcript}Thought:")
            res = self._generate([{"role": "user", "content": prompt}])
            text = "Thought:" + res.get("content", "")
            transcript += text + "\n"

            final = FINAL_RE.search(text)
            if final:
                self._emit("agent_end", turns=turns)
                return AgentResult(content=self._strip_think(final.group(1).strip()),
                                   tool_results=tool_results, turns=turns)
            m_act = ACT_RE.search(text)
            if not m_act:
                transcript += "Observation: فرمت اشتباه — باید Action یا Final Answer بدهی.\n"
                continue
            name = m_act.group(1).strip()
            m_in = INPUT_RE.search(text)
            args = m_in.group(1).strip() if m_in else "{}"
            if self._executor is None:
                transcript += "Observation: خطا — executor ابزار وصل نیست.\n"
                continue
            tr = self._executor.execute(ToolCall(name=name, arguments=args))
            tool_results.append(tr)
            transcript += f"Observation: {'✅' if tr.success else '❌'} {tr.content[:2000]}\n"

        self._emit("agent_end", turns=turns, max_turns_exceeded=True)
        return AgentResult(content="به سقف گام‌ها رسیدم. خلاصه مشاهدات:\n" + transcript[-2000:],
                           tool_results=tool_results, turns=turns,
                           metadata={"max_turns_exceeded": True})

    def _user_text(self, ctx: AgentContext) -> str:
        for m in reversed(ctx.conversation.messages):
            if m.role == "user":
                return m.content
        return ""

    def _describe_tools(self, names: List[str]) -> str:
        if self._executor is None:
            return "(ابزاری ثبت نشده)"
        lines = []
        for n, t in self._executor.tools.items():
            if names and n not in names:
                continue
            s = t.spec
            lines.append(f"- {s.name}: {s.description} | پارامترها: {json.dumps(s.parameters.get('properties', {}), ensure_ascii=False)[:400]}")
        return "\n".join(lines) or "(ابزاری ثبت نشده)"
