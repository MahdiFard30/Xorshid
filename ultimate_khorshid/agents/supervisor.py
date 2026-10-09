"""SupervisorAgent — ارکستراسیون چندایجنتی واقعی.

تسک را به گام‌ها می‌شکند، هر گام را به مناسب‌ترین ساب‌ایجنت می‌سپارد،
یافته‌ها روی Blackboard مشترک می‌روند و در پایان جمع‌بندی می‌شود.
مسیریابی قاعده‌محور است تا حتی با موتور آفلاین هم کار کند.
"""

from __future__ import annotations

import re
from typing import Any, List

from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.core.registry import AgentRegistry

# (ایجنت، کلیدواژه‌ها) — ترتیب = اولویت
ROUTES = [
    ("quiz", ("آزمون", "سوال", "سؤال", "تست سایت", "quiz", "فرم سایت")),
    ("researcher", ("تحقیق", "research", "مقایسه", "بررسی", "تحلیل بازار", "investigate")),
    ("codeact", ("کد", "اسکریپت", "پایتون", "برنامه", "code", "script", "python")),
    ("planner", ("چند مرحله", "پلن", "برنامه‌ریزی", "step by step")),
]


def route_step(step: str) -> str:
    s = step.lower()
    for agent, keywords in ROUTES:
        if any(k.lower() in s for k in keywords):
            if AgentRegistry.contains(agent):
                return agent
    return "computer" if AgentRegistry.contains("computer") else "react"


def split_task(query: str, max_steps: int = 6) -> List[str]:
    q = (query or "").strip()
    if not q:
        return []
    # خطوط شماره‌دار یا چندخطی
    lines = [ln.strip(" -•\t") for ln in q.splitlines() if ln.strip()]
    numbered = [re.sub(r"^[\d۰-۹]+\s*[\).\:\-]\s*", "", ln) for ln in lines]
    if len(numbered) > 1:
        return [s for s in numbered if len(s) > 2][:max_steps]
    # جدا با «و بعد/سپس/then»
    parts = re.split(r"\s+(?:و بعد|سپس|بعدش|then|and then)\s+", q)
    parts = [p.strip() for p in parts if len(p.strip()) > 2]
    if len(parts) > 1:
        return parts[:max_steps]
    return [q]


@AgentRegistry.register("supervisor")
class SupervisorAgent(ToolUsingAgent):
    agent_id = "supervisor"

    def run(self, ctx: AgentContext) -> AgentResult:
        from ultimate_khorshid.core.blackboard import Blackboard, current_board
        from ultimate_khorshid.core.types import Conversation
        self._emit("agent_start")
        user_q = ""
        for m in reversed(ctx.conversation.messages):
            if m.role == "user":
                user_q = m.content
                break
        steps = split_task(user_q)
        if not steps:
            return AgentResult(content="کاری گفته نشد قربان.", metadata={"agent": "supervisor"})
        board = current_board() or Blackboard()
        board.write("task", user_q[:500], author="supervisor")
        all_results: List[Any] = []
        outs: List[str] = []
        routes: List[str] = []
        for i, step in enumerate(steps, 1):
            name = route_step(step)
            routes.append(f"{i}:{name}")
            try:
                cls = AgentRegistry.get(name)
                sub = cls(self._engine, self._model, bus=self._bus,
                          temperature=self._temperature, max_tokens=self._max_tokens,
                          system_prompt=self._system_prompt, max_turns=6,
                          executor=self._executor)
            except Exception as e:
                outs.append(f"**گام {i} ({name}):** ❌ ساخت ایجنت نشد: {e}")
                continue
            sub_ctx = AgentContext(conversation=Conversation(), tools=ctx.tools,
                                   memory_results=ctx.memory_results)
            sub_ctx.conversation.add(
                "user", f"{step}\n(زمینه: {user_q[:300]})\n[یافته‌های قبلی]\n{board.summary(800)}")
            try:
                r = sub.run(sub_ctx)
                board.write(f"step{i}", r.content[:800], author=name)
                all_results.extend(r.tool_results)
                outs.append(f"**گام {i} [{name}]: {step[:80]}**\n{r.content[:1200]}")
            except Exception as e:
                outs.append(f"**گام {i} ({name}):** ❌ {e}")
        self._emit("agent_end", turns=len(steps))
        body = ("## 🧠 گزارش سوپروایزر\n\n*مسیرها: " + ", ".join(routes) + "*\n\n"
                + "\n\n".join(outs))
        return AgentResult(content=body, tool_results=all_results, turns=len(steps),
                           metadata={"agent": "supervisor", "steps": steps,
                                     "routes": routes, "board": board.all()})
