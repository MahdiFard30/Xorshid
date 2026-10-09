"""ComputerAgent — ⭐ ایجنت کامپیوتری همه‌کاره (پیش‌فرض خورشید نهایی).

ترکیب orchestrator + حافظه خودکار + todo خودکار + خلاصه فارسی شیک.
با هر موتوری کار می‌کند (mock/ollama/openai).
"""

from __future__ import annotations

import json
import re
from ultimate_khorshid.core.types import ToolCall


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


def direct_site_request(text):
    """Only explicit, single-action opening requests; leave other tasks to the agent."""
    text = text.strip().lower().replace("ي", "ی").replace("ك", "ک")
    text = text.replace("یوتوب", "یوتیوب").replace("يوتيوب", "یوتیوب")
    if re.search(r"نکن|نبند|ببند|نمی|چطور|چگونه|اگر|وقتی|آموزش|جستجو|جست‌وجو|پخش|کلیک|\b(?:don't|how|if|when|search|play|click|close)\b", text):
        return None
    verb = re.search(r"باز\s*(?:کن|بکن)(?![آ-ی])|بازش\s*کن(?![آ-ی])|\b(?:open|launch)\b", text)
    if not verb:
        return None
    sites = {"یوتیوب": "https://www.youtube.com/", "youtube": "https://www.youtube.com/",
             "گوگل": "https://www.google.com/", "google": "https://www.google.com/"}
    url_match = re.search(r"https?://[^\s<>]+", text)
    if url_match:
        target = url_match.group().rstrip(".,!؟،")
        remainder = text[:url_match.start()] + " " + text[url_match.end():]
    else:
        matches = [(key, url) for key, url in sites.items() if re.search(r"(?<!\w)" + re.escape(key) + r"(?!\w)", text)]
        if len(matches) != 1:
            return None
        key, target = matches[0]
        remainder = re.sub(r"(?<!\w)" + re.escape(key) + r"(?!\w)", " ", text)
    remainder = re.sub(r"باز\s*(?:کن|بکن)(?![آ-ی])|بازش\s*کن(?![آ-ی])|\b(?:open|launch)\b", " ", remainder)
    fillers = {"لطفا", "لطفاً", "خورشید", "سایت", "رو", "را", "تو", "توی", "در", "مرورگر",
               "پنجره", "قابل", "مشاهده", "برای", "من", "برام", "الان", "یه", "یک", "جدید",
               "please", "in", "the", "browser", "for", "me", "a", "new", "window"}
    words = re.findall(r"[\w‌]+", remainder)
    if any(word not in fillers for word in words):
        return None
    return target


def direct_app_request(text):
    """Route only an explicit single request to open the verified Telegram app."""
    text = text.strip().lower().replace("ي", "ی").replace("ك", "ک")
    text = text.replace("تلگرامو", "تلگرام رو")
    if re.search(r"نکن|نمی|نباید|ببند|چطور|چگونه|اگر|وقتی|آموزش|پیام|بفرست|ارسال|جستجو|وب|سایت|مرورگر|\b(?:don't|how|if|when|close|send|message|web|browser|search)\b", text):
        return None
    verb = r"باز\s*(?:کن|بکن)(?![آ-ی])|بازش\s*کن(?![آ-ی])|\b(?:open|launch)\b"
    name = r"(?<!\w)(?:تلگرام|telegram)(?!\w)"
    if len(re.findall(name, text)) != 1 or len(re.findall(verb, text)) != 1:
        return None
    remaining = re.sub(name, " ", re.sub(verb, " ", text))
    fillers = {"لطفا", "لطفاً", "خورشید", "رو", "را", "برای", "من", "برام", "الان",
               "برنامه", "اپ", "please", "for", "me", "the", "app"}
    if any(word not in fillers for word in re.findall(r"[\w‌]+", remaining)):
        return None
    return "telegram-desktop"


@AgentRegistry.register("computer")
class ComputerAgent(ToolUsingAgent):
    agent_id = "computer"

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        user_text = next((m.content for m in reversed(ctx.conversation.messages) if m.role == "user"), "")
        app_target = direct_app_request(user_text)
        site_target = direct_site_request(user_text) if not app_target else None
        if app_target or site_target:
            tool_name = "open_app" if app_target else "open_url"
            target = app_target or site_target
            if self._executor is None:
                return AgentResult(content="ابزار اجرا به خورشید وصل نیست؛ برنامه یا سایت باز نشد.", turns=0)
            params = {"target": target} if app_target else {"url": target}
            print(f"[Action] {tool_name}: {target}", flush=True)
            tr = self._executor.execute(ToolCall(name=tool_name, arguments=json.dumps(params)))
            print(f"[Action] {'OK' if tr.success else 'ERROR'}: {tr.content}", flush=True)
            self._emit("agent_end", turns=0)
            return AgentResult(content=tr.content, tool_results=[tr], turns=0,
                               metadata={"agent": "computer", "direct_action": tool_name})
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
