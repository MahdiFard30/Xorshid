"""ResearchAgent — تحقیق عمیق چندپرهشی با استناد (مثل deep_research در OpenJarvis)."""

from __future__ import annotations

import json
from typing import List

from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.core.registry import AgentRegistry
from ultimate_khorshid.core.types import ToolCall, ToolResult


@AgentRegistry.register("researcher")
@AgentRegistry.register("deep_research")
class ResearchAgent(ToolUsingAgent):
    agent_id = "researcher"
    max_rounds: int = 3

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        user_q = next((m.content for m in reversed(ctx.conversation.messages) if m.role == "user"), "")
        results: List[ToolResult] = []
        evidence: List[str] = []
        queries = self._make_queries(user_q)
        for q in queries[:4]:
            if self._executor and "web_search" in self._executor.tools:
                tr = self._executor.execute(ToolCall(name="web_search",
                                                     arguments=json.dumps({"query": q, "count": 5}, ensure_ascii=False)))
                results.append(tr)
                if tr.success:
                    evidence.append(f"🔎 {q}\n{tr.content[:1500]}")
        # خواندن حداکثر ۲ صفحه اول
        import re
        urls = re.findall(r"https?://[^\s)«»\"']+", "\n".join(evidence))[:2]
        for u in urls:
            if self._executor and "web_fetch" in self._executor.tools:
                tr = self._executor.execute(ToolCall(name="web_fetch",
                                                     arguments=json.dumps({"url": u, "max_chars": 4000})))
                results.append(tr)
                if tr.success:
                    evidence.append(f"📄 {u}\n{tr.content[:2500]}")
        # سنتز نهایی
        synth_prompt = ("تو یک پژوهشگر فارسی‌زبان هستی. با توجه به شواهد زیر، یک گزارش تحقیقی ساخت‌یافته بنویس: "
                        "خلاصه، یافته‌های کلیدی (بولت)، نتیجه‌گیری، و منابع (لینک‌ها). فارسی روان.\n\n"
                        f"سؤال: {user_q[:800]}\n\nشواهد:\n" + "\n\n---\n\n".join(evidence)[:9000])
        try:
            res = self._generate([{"role": "user", "content": synth_prompt}])
            content = self._strip_think(res.get("content", "")) or "شواهد کافی نبود."
        except Exception as e:
            content = f"خطا در سنتز: {e}\n\nشواهد خام:\n" + "\n".join(evidence)[:3000]
        self._emit("agent_end", turns=len(results))
        return AgentResult(content=f"## 🔬 گزارش تحقیق\n\n{content}", tool_results=results,
                           turns=len(results), metadata={"queries": queries})

    def _make_queries(self, q: str) -> List[str]:
        try:
            res = self._generate([{"role": "user", "content":
                f"برای تحقیق درباره «{q[:300]}» دقیقاً ۳ پرسش جست‌وجوی وب (فارسی/انگلیسی) تولید کن؛ هر خط یک پرسش، بدون شماره."}])
            lines = [l.strip("- •*0123456789.) ") for l in res.get("content", "").splitlines()]
            qs = [l for l in lines if len(l) > 3][:3]
            return qs or [q]
        except Exception:
            return [q]
