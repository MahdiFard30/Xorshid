"""PlannerAgent — برنامه‌ریزی چندمرحله‌ای + اجرای گام‌به‌گام با orchestrator داخلی."""

from __future__ import annotations

import json
import re
from typing import List

from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.agents.orchestrator import OrchestratorAgent
from ultimate_khorshid.core.registry import AgentRegistry
from ultimate_khorshid.core.types import Conversation, ToolResult

PLAN_PROMPT = """تو یک برنامه‌ریز خبره هستی. درخواست کاربر را به گام‌های اجرایی کوچک بشکن.
فقط و فقط یک JSON معتبر با این ساختار برگردان (بدون توضیح اضافه):
{"steps": ["گام ۱ ...", "گام ۲ ...", ...]}
حداکثر ۸ گام. هر گام یک جمله شفاف و قابل اجرا.
درخواست: """


@AgentRegistry.register("planner")
class PlannerAgent(ToolUsingAgent):
    agent_id = "planner"

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        user_q = ""
        for m in reversed(ctx.conversation.messages):
            if m.role == "user":
                user_q = m.content
                break
        # ۱) تولید پلن
        try:
            res = self._generate([{"role": "user", "content": PLAN_PROMPT + user_q[:2000]}])
            steps = self._parse_steps(res.get("content", ""))
        except Exception:
            steps = []
        if not steps:
            steps = [user_q]  # fallback: تک‌گام
        # چک‌پوینت: ادامه از نیمه‌راه با metadata={"resume_id": ...}
        import uuid
        from ultimate_khorshid.core import checkpoint as Ck
        run_id = str(ctx.metadata.get("resume_id") or f"planner-{uuid.uuid4().hex[:8]}")
        outs_resumed: List[str] = []
        if ctx.metadata.get("resume_id"):
            st = Ck.load(run_id) or {}
            if st.get("steps"):
                steps = st["steps"]
            outs_resumed = st.get("outs", []) or []
        # ۲) اجرای گام‌ها با orchestrator
        all_results: List[ToolResult] = []
        outs: List[str] = list(outs_resumed)
        start_at = len(outs_resumed)
        worker = OrchestratorAgent(self._engine, self._model, bus=self._bus,
                                   temperature=self._temperature, max_tokens=self._max_tokens,
                                   system_prompt=self._system_prompt, max_turns=6,
                                   executor=self._executor)
        for i, step in enumerate(steps[:8], 1):
            if i <= start_at:
                continue  # قبلاً انجام شده (resume)
            sub = AgentContext(conversation=Conversation(), tools=ctx.tools)
            sub.conversation.add("user", f"گام {i} از {len(steps)} — {step}\n(زمینه اصلی: {user_q[:500]})")
            r = worker.run(sub)
            all_results.extend(r.tool_results)
            outs.append(f"**گام {i}: {step}**\n{r.content[:1200]}")
            try:
                Ck.save(run_id, {"agent": "planner", "query": user_q[:300],
                                 "steps": steps, "outs": outs})
            except Exception:
                pass
        self._emit("agent_end", turns=len(steps))
        body = "## 📋 اجرای پلن\n\n" + "\n\n".join(outs)
        return AgentResult(content=body, tool_results=all_results, turns=len(steps),
                           metadata={"steps": steps, "checkpoint_id": run_id})

    def _parse_steps(self, text: str):
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            # fallback: خطوط شماره‌دار
            lines = [re.sub(r"^[\d\-*.)\s]+", "", l).strip() for l in text.splitlines()]
            return [l for l in lines if len(l) > 3][:8]
        try:
            data = json.loads(m.group(0))
            steps = data.get("steps", [])
            return [str(s)[:300] for s in steps if str(s).strip()][:8]
        except Exception:
            return []
