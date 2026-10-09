"""SimpleAgent — گپ تک‌نوبتی بدون ابزار."""

from __future__ import annotations

from ultimate_khorshid.agents.base import AgentContext, AgentResult, BaseAgent
from ultimate_khorshid.core.registry import AgentRegistry


@AgentRegistry.register("simple")
class SimpleAgent(BaseAgent):
    agent_id = "simple"

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        msgs = self._build_messages(ctx)
        res = self._generate(msgs)
        self._emit("agent_end", turns=1)
        return AgentResult(content=self._strip_think(res.get("content", "")), turns=1,
                           metadata={"model": self._model})
