"""AutonomousAgent (operative) — ایجنت خودمختار هدف‌محور با حلقه تا اتمام.

هدف + معیار اتمام می‌گیرد و تا رسیدن به هدف (یا سقف دور) ادامه می‌دهد.
"""

from __future__ import annotations

from typing import List

from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.agents.orchestrator import OrchestratorAgent
from ultimate_khorshid.core.registry import AgentRegistry
from ultimate_khorshid.core.types import Conversation, ToolResult

JUDGE_PROMPT = """تو داور اتمام کار هستی. با توجه به «هدف» و «آخرین خروجی»، فقط یکی را برگردان:
- DONE: <خلاصه نتیجه>  (اگر هدف محقق شده)
- CONTINUE: <دستور گام بعدی>  (اگر هنوز کار مانده)
"""


@AgentRegistry.register("autonomous")
@AgentRegistry.register("operative")
class AutonomousAgent(ToolUsingAgent):
    agent_id = "autonomous"
    max_rounds: int = 5

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        goal = ctx.metadata.get("goal") or next(
            (m.content for m in reversed(ctx.conversation.messages) if m.role == "user"), "")
        rounds = min(int(ctx.metadata.get("rounds", self.max_rounds) or self.max_rounds), 10)
        all_tools: List[ToolResult] = []
        history: List[str] = []
        worker = OrchestratorAgent(self._engine, self._model, bus=self._bus,
                                   temperature=self._temperature, max_tokens=self._max_tokens,
                                   system_prompt=self._system_prompt, max_turns=8,
                                   executor=self._executor)
        final = ""
        for r in range(1, rounds + 1):
            sub = AgentContext(conversation=Conversation(), tools=ctx.tools)
            context_txt = "\n".join(history[-4:])
            sub.conversation.add("user", f"🎯 هدف کلی: {goal[:1000]}\n\nپیشرفت قبلی:\n{context_txt or '(شروع)'}\n\nوظیفه این دور (دور {r} از {rounds}): یک قدم ملموس به سمت هدف بردار.")
            out = worker.run(sub)
            all_tools.extend(out.tool_results)
            history.append(f"دور {r}: {out.content[:800]}")
            final = out.content
            # داوری اتمام
            try:
                judge = self._generate([{"role": "user", "content":
                    JUDGE_PROMPT + f"\nهدف: {goal[:500]}\nآخرین خروجی: {out.content[:1500]}"}])
                verdict = judge.get("content", "CONTINUE").strip()
            except Exception:
                verdict = "CONTINUE"
            if verdict.upper().startswith("DONE"):
                final = verdict[5:].strip() or final
                break
        self._emit("agent_end", turns=rounds)
        body = f"## 🤖 اجرای خودمختار ({len(history)} دور)\n\n" + "\n\n".join(
            f"**{h}**" for h in history) + f"\n\n### نتیجه نهایی\n{final[:3000]}"
        return AgentResult(content=body, tool_results=all_tools, turns=len(history),
                           metadata={"goal": goal[:300]})
