"""QuizSolverAgent — حل خودکار سؤال‌های تستی/فرم یک صفحه وب.

گردش: باز کردن صفحه ← استخراج فرم‌ها ← جواب هر سؤال با مغز LLM ←
کلیک گزینه صحیح ← گزارش نهایی.
نکته: جواب درست نیاز به مغز واقعی (gemini/ollama/openai) دارد.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List

from ultimate_khorshid.agents.base import AgentContext, AgentResult, ToolUsingAgent
from ultimate_khorshid.core.registry import AgentRegistry
from ultimate_khorshid.core.types import ToolCall, ToolResult

ASK_PROMPT = """تو در حال حل یک آزمون هستی. فقط و فقط متن دقیق «گزینه صحیح» را برگردان (بدون توضیح).
سؤال: {q}
گزینه‌ها:
{opts}
پاسخ (عین متن گزینه):"""


@AgentRegistry.register("quiz")
class QuizSolverAgent(ToolUsingAgent):
    agent_id = "quiz"

    def run(self, ctx: AgentContext) -> AgentResult:
        self._emit("agent_start")
        results: List[ToolResult] = []
        log: List[str] = []

        def call(name: str, **kw: Any) -> ToolResult:
            tr = self._executor.execute(ToolCall(
                name=name, arguments=json.dumps(kw, ensure_ascii=False))) if self._executor else ToolResult(
                tool_name=name, content="executor نیست", success=False)
            results.append(tr)
            return tr

        # ۱) آدرس صفحه؟
        url = ctx.metadata.get("url", "") or self._find_url(ctx)
        if url:
            tr = call("browser_open", url=url)
            log.append(f"🌐 باز کردن صفحه: {'✅' if tr.success else '❌ ' + tr.content[:150]}")
            if not tr.success:
                self._emit("agent_end", turns=1)
                return AgentResult(content="\n".join(log), tool_results=results, turns=1)

        # ۲) استخراج فرم‌ها
        tr = call("browser_forms")
        if not tr.success:
            self._emit("agent_end", turns=2)
            return AgentResult(
                content=f"❌ نتوانستم فرم‌ها را بخوانم:\n{tr.content[:500]}",
                tool_results=results, turns=2)
        fields = self._parse_fields(tr.content)
        radios = [f for f in fields if f["type"] == "radio"]
        checks = [f for f in fields if f["type"] == "checkbox"]
        selects = [f for f in fields if f["type"] == "select"]
        texts = [f for f in fields if f["type"] in ("text", "textarea", "email", "number")]
        log.append(f"📝 پیدا شد: {len(radios)} تستی، {len(checks)} چک‌باکس، "
                   f"{len(selects)} دراپ‌داون، {len(texts)} متنی")

        # ۳) گروه‌بندی رادیوها theo نزدیک‌به‌هم (هر گروه = یک سؤال)
        groups = self._group_radios(radios, tr.content)
        max_q = min(int(ctx.metadata.get("max_questions", 30) or 30), 50)
        answered = 0
        for gi, grp in enumerate(groups[:max_q], 1):
            q_text = grp["question"] or f"سؤال {gi}"
            opts = [o for o in grp["options"] if o["label"]]
            if not opts:
                continue
            # ۴) پرسش از مغز
            try:
                res = self._generate([{"role": "user", "content": ASK_PROMPT.format(
                    q=q_text[:600],
                    opts="\n".join(f"- {o['label'][:150]}" for o in opts))}])
                answer = self._strip_think(res.get("content", "")).strip().strip("\"'«»")[:150]
            except Exception as e:
                log.append(f"❌ سؤال {gi}: خطای مغز ({e})")
                continue
            # ۵) تطبیق جواب با گزینه و کلیک
            target = self._match(answer, opts)
            if target is None:
                log.append(f"⚠️ سؤال {gi}: جواب «{answer[:60]}» با گزینه‌ای جور نشد.")
                continue
            ctr = call("browser_check", ref=target["i"])
            if ctr.success:
                answered += 1
                log.append(f"✅ سؤال {gi}: «{target['label'][:70]}»")
            else:
                log.append(f"❌ سؤال {gi}: کلیک نشد.")

        # ۶) دکمه ثبت؟
        submit = self._find_submit(ctx)
        if submit and ctx.metadata.get("submit", False):
            ctr = call("browser_click", ref=submit, by="index")
            log.append(f"📨 ثبت: {'✅' if ctr.success else '❌'}")
        elif submit:
            log.append(f"💡 دکمه ثبت پیدا شد (ایندکس {submit}) — برای ثبت نهایی بگو «ثبت کن».")

        self._emit("agent_end", turns=answered + 2)
        head = f"## 📝 گزارش حل آزمون\n\n**جواب داده شد: {answered} سؤال**\n\n"
        return AgentResult(content=head + "\n".join(log), tool_results=results,
                           turns=answered + 2, metadata={"answered": answered})

    # -- helpers --
    def _find_url(self, ctx: AgentContext) -> str:
        for m in reversed(ctx.conversation.messages):
            f = re.search(r"https?://[^\s)«»\"']+", m.content)
            if f:
                return f.group(0)
        return ""

    def _parse_fields(self, text: str) -> List[Dict[str, Any]]:
        fields = []
        for line in text.splitlines():
            m = re.match(r"\[(\d+)\]\s*\(([^)]+)\)\s*(.*)", line.strip())
            if m:
                fields.append({"i": m.group(1), "type": m.group(2), "rest": m.group(3)})
        return fields

    def _group_radios(self, radios: List[Dict], forms_text: str) -> List[Dict[str, Any]]:
        """گروه‌بندی ساده: رادیوهای پشت‌سرهم با value مشابه = یک سؤال."""
        groups: List[Dict[str, Any]] = []
        cur: Dict[str, Any] = {"question": "", "options": []}
        for r in radios:
            label = re.sub(r"\s*\[.\]\s*value=.*$", "", r["rest"]).strip()
            opt = {"i": r["i"], "label": label}
            if not cur["options"]:
                cur["options"].append(opt)
            else:
                # اگر ایندکس‌ها پشت سر هم‌اند، همان گروه
                if int(r["i"]) == int(cur["options"][-1]["i"]) + 1:
                    cur["options"].append(opt)
                else:
                    groups.append(cur)
                    cur = {"question": "", "options": [opt]}
            # حدس متن سؤال از لیبل مشترک ابتدایی
            if not cur["question"] and ":" in label:
                cur["question"] = label.split(":")[0][:200]
        if cur["options"]:
            groups.append(cur)
        # اگر همه یکی شدند ولی زیادند، همان را نگه دار (تک‌سؤالی‌ها هم پوشش داده می‌شوند)
        return groups

    def _match(self, answer: str, opts: List[Dict[str, str]]) -> Dict | None:
        a = answer.strip().lower()
        if not a:
            return None
        # ۱) تطابق دقیق/زیررشته‌ای
        for o in opts:
            lo = o["label"].lower()
            if a == lo or (len(a) > 3 and (a in lo or lo in a)):
                return o
        # ۲) حرف گزینه (الف/ب/ج یا A/B/C یا ۱/۲/۳)
        letters = ["الف", "ب", "ج", "د", "a", "b", "c", "d", "1", "2", "3", "4",
                   "۱", "۲", "۳", "۴"]
        for idx, L in enumerate(letters[:len(opts)]):
            if a.startswith(L):
                return opts[idx] if idx < len(opts) else None
        # ۳) بیشترین کلمات مشترک
        best, score = None, 0
        aw = set(a.split())
        for o in opts:
            s = len(aw & set(o["label"].lower().split()))
            if s > score:
                best, score = o, s
        return best if score > 0 else None

    def _find_submit(self, ctx: AgentContext) -> str:
        return ""  # در نسخه فعلی: کاربر با browser_click ثبت می‌کند
