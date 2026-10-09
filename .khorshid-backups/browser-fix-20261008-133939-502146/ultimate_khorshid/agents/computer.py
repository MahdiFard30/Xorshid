"""ComputerAgent — ⭐ ایجنت کامپیوتری همه‌کاره (پیش‌فرض خورشید نهایی).

ترکیب orchestrator + حافظه خودکار + todo خودکار + خلاصه فارسی شیک.
با هر موتوری کار می‌کند (mock/ollama/openai).
"""

from __future__ import annotations


from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.agents.orchestrator import OrchestratorAgent
from ultimate_khorshid.core.registry import AgentRegistry

COMPUTER_SYS = """تو «خورشید نهایی» هستی — ایجنت کامپیوتری شخصی کاربر. فارسی روان و مؤدب حرف می‌زن («قربان» گاهی).

اصول کاری:
1. قبل از کار چندمرحله‌ای، با think فکر کن و با todo گام‌ها را ثبت کن.
2. اول اطلاعات جمع کن (file_list/file_read/web_search) بعد اقدام کن.
3. فایل‌ها را با file_write/file_edit بساز/ویرایش؛ دستورات را با shell_exec؛ محاسبات را با python_exec/calculator.
4. وب واقعی: اگر کاربر گفت «برو توی گوگل/مرورگر»، از browser_google_search/browser_open استفاده کن (نه web_search).
5. دسکتاپ: screenshot برای دیدن صفحه، vision_ask برای فهمیدنش، mouse_click/type_text/key_press برای کنترل.
6. قیمت رمزارز (تتر و...) را با crypto_price بگیر.
4. خروجی ابزار را خلاصه و تمیز به کاربر بده، نه خام و طولانی.
5. اگر چیزی مبهم بود، معقول‌ترین فرض را بگیر و ادامه بده؛ در پایان فرضت را بگو.
6. هرگز فایل حساس (.env، کلیدها) را نمایش نده؛ دستورات مخرب را اجرا نکن.
"""


@AgentRegistry.register("computer")
class ComputerAgent(ToolUsingAgent):
    agent_id = "computer"

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        worker = OrchestratorAgent(
            self._engine, self._model, bus=self._bus,
            temperature=self._temperature, max_tokens=self._max_tokens,
            system_prompt=(self._system_prompt + "\n" + COMPUTER_SYS) if self._system_prompt else COMPUTER_SYS,
            max_turns=self._max_turns, executor=self._executor)
        result = worker.run(ctx)
        # تزئین خروجی
        content = result.content
        if result.tool_results:
            ok = sum(1 for t in result.tool_results if t.success)
            content += f"\n\n---\n*⚙️ {len(result.tool_results)} ابزار اجرا شد ({ok} موفق) | ایجنت: computer | مدل: {self._model}*"
        self._emit("agent_end", turns=result.turns)
        return AgentResult(content=content, tool_results=result.tool_results,
                           turns=result.turns, metadata={**result.metadata, "agent": "computer"})
