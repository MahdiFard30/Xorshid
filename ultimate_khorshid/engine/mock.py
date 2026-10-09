"""MockEngine — موتور آفلاین هوشمند (بدون API) برای تست و اجرای دترمینیستیک.

این موتور یک «مغز قاعده‌محور» دارد: دستور کاربر را می‌فهمد و مستقیم tool_call
تولید می‌کند تا ایجنت‌ها حتی بدون LLM واقعی هم کار کنند. برای فارسی بهینه شده.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional
from ultimate_khorshid.core.registry import EngineRegistry
from ultimate_khorshid.engine.base import InferenceEngine


@EngineRegistry.register("mock")
class MockEngine(InferenceEngine):
    engine_id = "mock"
    supports_streaming = True

    # ---------- helpers ----------
    def _tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        return {"name": name, "arguments": json.dumps(args, ensure_ascii=False), "id": f"mock_{name}"}

    def _last_user(self, messages: List[Dict[str, Any]]) -> str:
        for m in reversed(messages):
            if m.get("role") == "user":
                c = m.get("content", "")
                return c if isinstance(c, str) else str(c)
        return ""

    def _has_tool_results(self, messages: List[Dict[str, Any]]) -> bool:
        return any(m.get("role") == "tool" for m in messages)

    # ---------- main ----------
    def generate(self, messages, model, *, tools=None, temperature=0.7, max_tokens=1024, **kw):
        tool_names = set()
        if tools:
            for t in tools:
                fn = t.get("function", t)
                if fn.get("name"):
                    tool_names.add(fn["name"])

        user_q = self._last_user(messages)

        # پرامپت‌های متای ایجنت‌ها (ReAct/Planner/Researcher/...) — پاسخ ساخت‌یافته
        meta = self._meta_respond(user_q)
        if meta is not None:
            return {"content": meta, "tool_calls": [], "finish_reason": "stop", "usage": {}}

        # اگر قبلاً ابزار اجرا شده → جمع‌بندی نهایی
        if self._has_tool_results(messages):
            last_tool, last_name = "", ""
            for m in reversed(messages):
                if m.get("role") == "tool":
                    last_tool = str(m.get("content", ""))[:3000]
                    last_name = str(m.get("name", ""))
                    break
            summary = self._summarize(user_q, last_tool)
            if last_name == "browser_forms" and re.search(r"(سوال|سؤال|جواب|تست|آزمون)", user_q):
                summary += ("\n\n💡 قدم اول انجام شد (فرم‌ها خوانده شدند). برای **حل کامل و انتخاب "
                            "گزینه‌های صحیح** به مغز واقعی نیاز است:\n"
                            "`export GEMINI_API_KEY=... KHORSHID_ENGINE=gemini` سپس:\n"
                            "`khorshid ask \"سوال‌های این صفحه را جواب بده\" --agent quiz`")
            return {"content": summary, "tool_calls": [], "finish_reason": "stop", "usage": {}}

        # وگرنه: تلاش برای تولید tool_call از روی متن
        # اگر پرامپت از جنس «گام پلنر» است، اول روی متن خود گام تمرکز کن
        m_step = re.search(r"گام\s*\d+\s*از\s*\d+\s*[—\-:]\s*(.+?)(?:\n|$)", user_q)
        focus_q = m_step.group(1).strip() if m_step else user_q
        call = self._plan_tool_call(focus_q, tool_names)
        if call is None and focus_q != user_q:
            call = self._plan_tool_call(user_q, tool_names)
        if call:
            thinking = f"می‌فهمم قربان. ابزار `{call['name']}` را اجرا می‌کنم."
            return {"content": thinking, "tool_calls": [call], "finish_reason": "tool_calls", "usage": {}}

        # بدون ابزار: پاسخ مستقیم
        return {"content": self._chat(user_q), "tool_calls": [], "finish_reason": "stop", "usage": {}}

    # ---------- meta prompts (از طرف ایجنت‌های planner/react/researcher/...) ----------
    def generate_stream(self, messages, model, *, tools=None, temperature=0.7,
                        max_tokens=1024, **kw):
        res = self.generate(messages, model, tools=tools, temperature=temperature,
                            max_tokens=max_tokens, **kw)
        text = str(res.get("content", ""))
        words = text.split(" ")
        buf = ""
        for w in words:
            buf += (w + " ")
            if len(buf) >= 40:
                yield {"delta": buf, "done": False}
                buf = ""
        if buf:
            yield {"delta": buf, "done": False}
        yield {"delta": "", "done": True, "result": res}

    def _meta_respond(self, q: str) -> Optional[str]:
        # ۱) ReAct: «سؤال کاربر: ...» + دستور Thought/Action
        if "Action Input" in q and "سؤال کاربر" in q:
            m = re.search(r"سؤال کاربر:\s*(.+?)(?:\n\n|\nThought:|$)", q, re.S)
            user_q = m.group(1).strip()[:800] if m else q[:300]
            obs = re.findall(r"Observation:\s*(.+?)(?:\nThought:|\Z)", q, re.S)
            if obs:
                last = obs[-1].strip()[:1500]
                return f"پاسخ را از مشاهده استخراج کردم.\nFinal Answer: {last}"
            # ابزار مناسب را حدس بزن (با همه ابزارهای فرضی)
            fake_avail = {"calculator", "datetime_now", "sysinfo", "process_list", "file_list",
                          "file_read", "file_write", "file_search", "shell_exec", "python_exec",
                          "web_search", "web_fetch", "memory_store", "memory_search", "git", "todo"}
            call = self._plan_tool_call(user_q, fake_avail)
            if call:
                return (f"باید از ابزار استفاده کنم.\nAction: {call['name']}\n"
                        f"Action Input: {call['arguments']}")
            return f"نیازی به ابزار نیست.\nFinal Answer: {self._chat(user_q)[:800]}"

        # ۲) Planner: درخواست JSON گام‌ها
        if '{"steps"' in q and "گام" in q:
            m = re.search(r"درخواست:\s*(.+)$", q, re.S)
            req = m.group(1).strip()[:600] if m else q[-600:]
            parts = [p.strip() for p in re.split(r"\s+و\s+|،|;|\n", req) if len(p.strip()) > 4]
            steps = parts[:4] if len(parts) > 1 else [req]
            return json.dumps({"steps": steps[:6]}, ensure_ascii=False)

        # ۳) Researcher: تولید ۳ پرسش جست‌وجو
        if "پرسش جست‌وجوی وب" in q and "هر خط یک پرسش" in q:
            m = re.search(r"[«\"](.+?)[»\"]", q, re.S)
            topic = m.group(1).strip()[:200] if m else "موضوع"
            return f"{topic}\n{topic} آخرین اخبار\n{topic} بررسی و مقایسه"

        # ۴) Researcher: سنتز گزارش از شواهد
        if "پژوهشگر فارسی‌زبان" in q and "شواهد:" in q:
            ev = q.split("شواهد:", 1)[1][:6000] if "شواهد:" in q else ""
            m = re.search(r"سؤال:\s*(.+?)\n", q)
            topic = m.group(1).strip()[:200] if m else "موضوع"
            if not ev.strip():
                return f"درباره «{topic}» شواهد کافی از وب به دست نیامد (احتمالاً اینترنت محدود است)."
            return (f"## خلاصه\nدرباره «{topic}» شواهد زیر گردآوری شد.\n\n"
                    f"## یافته‌های کلیدی\n{ev[:4000]}\n\n"
                    f"## نتیجه‌گیری\nبا توجه به شواهد بالا، یافته‌ها استخراج و منابع ذکر شدند.")

        # ۵) Autonomous: داور اتمام DONE/CONTINUE
        if "CONTINUE:" in q and "آخرین خروجی:" in q:
            m = re.search(r"آخرین خروجی:\s*(.+)$", q, re.S)
            last = m.group(1).strip() if m else ""
            if any(s in last for s in ("✅", "[OK]", "انجام شد", "نوشته شد", "ذخیره شد")):
                return f"DONE: {last[:600]}"
            if "هدف" in q and len(last) > 50:
                return f"DONE: {last[:600]}"
            return "CONTINUE: با ابزار مناسب یک قدم دیگر بردار و نتیجه را گزارش بده."

        return None

    # ---------- rule brain ----------
    def _plan_tool_call(self, q: str, available: set) -> Optional[Dict[str, Any]]:
        ql = q.lower()

        def has(*names: str) -> Optional[str]:
            for n in names:
                if n in available:
                    return n
            return None

        # --- محاسبات ---
        m = re.search(r"(?:حساب کن|محاسبه|calculate|calc)\s*[:：]?\s*(.+)", q, re.I)
        if m and (t := has("calculator")):
            return self._tool(t, {"expression": m.group(1).strip()})
        if re.fullmatch(r"[\d\s\+\-\*\/\.\(\)\^٪%×÷]+", q.strip()) and len(q.strip()) >= 3 and (t := has("calculator")):
            expr = q.strip().replace("×", "*").replace("÷", "/").replace("٪", "/100").replace("^", "**")
            return self._tool(t, {"expression": expr})

        # --- لیست فایل‌ها ---
        m = re.search(r"(?:لیست|فهرست|نمایش).*?(?:فایل|پوشه|دایرکتوری|فولدر)|(?:ls|dir|list files)", q, re.I)
        if m and (t := has("file_list")):
            path = self._extract_path(q) or "."
            return self._tool(t, {"path": path})

        # --- خواندن فایل ---
        m = re.search(r"(?:بخوان|باز کن|نمایش بده|نشان بده|read|cat)\s+(?:فایل\s+)?[«\"']?([^\s«»\"']+)", q, re.I)
        if m and (t := has("file_read")):
            return self._tool(t, {"path": m.group(1).strip()})

        # --- نوشتن فایل: «بنویس در X: محتوا» ---
        m = re.search(r"(?:بنویس|بساز|ایجاد کن|write|create)\s+(?:در|داخل|فایل)?\s*[«\"']?([^\s:«»\"']+)[»\"']?\s*[:：]?\s*(.*)", q, re.I | re.S)
        if m and len(m.group(1)) > 1 and (t := has("file_write")):
            content = m.group(2).strip() or f"ساخته‌شده توسط خورشید از روی دستور: {q[:100]}"
            return self._tool(t, {"path": m.group(1).strip(), "content": content})

        # --- جست‌وجو در فایل‌ها ---
        m = re.search(r"(?:جستجو|پیدا|grep|search).*?(?:در|inside)\s*[«\"']?([^\s«»\"']+)", q, re.I)
        if m and (t := has("file_search")):
            path = m.group(1).strip()
            # الگو: قبل از «در»، یا بعد از مسیر («کلمه X»)، یا داخل گیومه
            m2 = re.search(r"(?:جستجو|پیدا کن|grep)\s+[«\"']?(.+?)[»\"']?\s+(?:در|داخل)", q, re.I)
            pattern = m2.group(1).strip() if m2 else ""
            if not pattern:
                m3 = re.search(r"(?:کلمه|الگو|pattern)\s*[«\"']?(.+?)[»\"']?\s*$", q, re.I)
                pattern = m3.group(1).strip() if m3 else ""
            if not pattern:
                mq = re.findall(r"[«\"']([^«»\"']+)[»\"']", q)
                pattern = mq[0].strip() if mq else ""
            if pattern:
                return self._tool(t, {"pattern": pattern, "path": path})
            # بدون الگو: به‌جای جست‌وجوی جعلی، راهنمایی متنی بده
            return None

        # --- اجرای شل ---
        m = re.search(r"(?:اجرا کن|run|exec|execute)\s*[:：]?\s*(.+)", q, re.I | re.S)
        if m and (t := has("shell_exec")):
            return self._tool(t, {"command": m.group(1).strip()[:500]})
        # دستورات مستقیم شل
        if re.match(r"^\s*(ls|pwd|whoami|echo|cat|df|free|uptime|uname|date|pip list|python3? --version)\b", q) and (t := has("shell_exec")):
            return self._tool(t, {"command": q.strip()[:500]})

        # --- اجرای پایتون ---
        m = re.search(r"(?:پایتون|python)\s*[:：]?\s*(.+)", q, re.I | re.S)
        if m and len(m.group(1).strip()) > 2 and (t := has("python_exec")):
            return self._tool(t, {"code": m.group(1).strip()[:2000]})

        # --- مرورگر واقعی: «برو توی گوگل سرچ کن X» ---
        m = re.search(r"(?:گوگل|مرورگر|browser).{0,40}?(?:سرچ|جستجو)\s*کن\s*[:：]?\s*(.+)", q, re.I | re.S)
        if m and (t := has("browser_google_search")):
            query = re.sub(r"^(که|اینکه|ببین|لطفا|لطفاً)\s+", "", m.group(1).strip())[:300]
            return self._tool(t, {"query": query or q[:100]})
        if re.search(r"گوگل\s*(را|رو)?\s*باز\s*کن", q) and (t := has("browser_open")):
            return self._tool(t, {"url": "https://www.google.com"})
        m = re.search(r"(?:سایت|صفحه|وبسایت)\s+(.+?)\s*(?:را|رو)\s*(?:باز\s*کن|برو)", q, re.I)
        if m and (t := has("browser_open")):
            target = m.group(1).strip().strip("«»\"'")[:150]
            if "." in target and " " not in target:
                return self._tool(t, {"url": target})
            if (t2 := has("browser_google_search")):
                return self._tool(t2, {"query": target})

        # --- قیمت رمزارز (تتر و...) ---
        try:
            from ultimate_khorshid.tools.crypto import detect_coin
        except Exception:
            detect_coin = None  # type: ignore
        if detect_coin and (t := has("crypto_price")):
            coin = detect_coin(q) or detect_coin(q.upper())
            if coin and re.search(r"(قیمت|چنده|چند|نرخ|تتر|بیت|اتریوم|دوج|سولانا|ریپل|کریپتو|ارز)", q, re.I):
                cur = "IRT" if re.search(r"(تومان|تومان|irt|ریال)", q, re.I) else ""
                args: dict = {"symbol": coin[0]}
                if cur:
                    args["currency"] = cur
                return self._tool(t, args)

        # --- هواشناسی: «هوای تهران چطوره؟» ---
        if (t := has("weather")):
            try:
                from ultimate_khorshid.tools.weather import CITIES_FA
            except Exception:
                CITIES_FA = {}  # type: ignore
            city_hit = next((c for c in CITIES_FA if c in q), "")
            intent = re.search(r"(هوای?|آب.?وهوا|weather).{0,20}(چطور|چگونه|چنده|چند درجه|دما|پیش.?بینی|امروز|فردا|باران|برف|ابری|آفتابی)", q, re.I)
            if intent or (city_hit and re.search(r"(هوا|weather)", q, re.I)):
                return self._tool(t, {"city": city_hit or "تهران"})

        # --- دسکتاپ: اسکرین‌شات/بینایی/موس/کیبورد ---
        if re.search(r"(اسکرین\s*شات|اسکرینشات|عکس\s*از\s*صفحه|از\s*صفحه\s*عکس|صفحه\s*(را|رو)\s*ببین|screenshot)", q, re.I) and (t := has("screenshot")):
            return self._tool(t, {})
        m = re.search(r"(?:صفحه\s*(را|رو)\s*توصیف\s*کن|توصیف\s*کن.*صفحه|تو[یي]\s*صفحه\s*چ[یه]\s*(میبینی|می‌بینی|هست)|میبینی.*\?)", q, re.I)
        if m and (t := has("vision_ask")):
            return self._tool(t, {"question": "این صفحه را دقیق توصیف کن: چه برنامه‌ای باز است و چه چیزهایی دیده می‌شود؟"})
        m = re.search(r"(?:تایپ\s*کن|تایپ)\s*[:：]?\s*(.+)", q, re.I | re.S)
        if m and len(m.group(1).strip()) > 0 and (t := has("type_text")):
            return self._tool(t, {"text": m.group(1).strip()[:500], "clipboard_type": True})
        m = re.search(r"(?:کلید|دکمه)\s+(.+?)\s*(?:را|رو)\s*بزن", q, re.I)
        if m and (t := has("key_press")):
            return self._tool(t, {"key": m.group(1).strip().lower()[:20]})
        m = re.search(r"کلیک\s*کن(?:\s*(?:رو[یي]|در))?\s*\(?\s*(\d+)\s*[,،]\s*(\d+)\s*\)?", q)
        if m and (t := has("mouse_click")):
            return self._tool(t, {"x": int(m.group(1)), "y": int(m.group(2))})
        m = re.search(r"(?:برنامه|اپ|نرم‌افزار)\s+(.+?)\s*(?:را|رو)\s*باز\s*کن", q, re.I)
        if m and (t := has("open_app")):
            return self._tool(t, {"target": m.group(1).strip()[:100]})

        # --- آزمون: «سؤال‌های سایت را جواب بده» (قدم اول: خواندن فرم‌ها) ---
        if re.search(r"(سوال|سؤال).{0,30}(جواب|حل)|جواب\s*بده.*(سوال|سؤال|تست|آزمون)|حل\s*کن.*(تست|آزمون|کوئیز)", q, re.I):
            m_url = re.search(r"(https?://[^\s«»\"']+)", q)
            if m_url and (t := has("browser_open")):
                # اول صفحه را باز کن؛ قدم‌های بعد با ایجنت quiz و مغز واقعی
                return self._tool(t, {"url": m_url.group(1)})
            if (t := has("browser_forms")):
                return self._tool(t, {})

        # --- صوت: بگو / گوش بده ---
        m = re.search(r"^بگو\s*[:：]?\s*(.+)", q, re.I | re.S)
        if m and (t := has("speak")):
            return self._tool(t, {"text": m.group(1).strip()[:800]})
        m = re.search(r"(?:بخوان|تلفظ\s*کن|بلند\s*بخوان)\s*[:：]\s*(.+)", q, re.I | re.S)
        if m and (t := has("speak")):
            return self._tool(t, {"text": m.group(1).strip()[:800]})
        if re.search(r"(گوش\s*(بده|کن)|ضبط\s*کن\s*صدا|حرف\s*بزنم)", q, re.I) and (t := has("listen")):
            return self._tool(t, {"seconds": 6})

        # --- جست‌وجوی وب ---
        m = re.search(r"(?:جستجو کن|سرچ کن|search|گوگل کن)\s*(?:در اینترنت|در وب)?\s*[:：]?\s*(.+)", q, re.I | re.S)
        if m and (t := has("web_search")):
            return self._tool(t, {"query": m.group(1).strip()[:300]})

        # --- باز کردن/خواندن صفحه وب ---
        m = re.search(r"(https?://[^\s«»\"']+)", q)
        if m and (t := has("web_fetch")):
            return self._tool(t, {"url": m.group(1)})

        # --- حافظه: ذخیره ---
        m = re.search(r"(?:به خاطر بسپار|یادت بماند|save to memory|remember)\s*[:：]?\s*(.+)", q, re.I | re.S)
        if m and (t := has("memory_store")):
            return self._tool(t, {"text": m.group(1).strip()[:2000]})

        # --- حافظه: یادآوری ---
        if re.search(r"(یادت هست|به خاطر داری|خاطره|recall|what do you remember)", q, re.I) and (t := has("memory_search")):
            kw = re.sub(r"(یادت هست|به خاطر داری|درباره|راجع به|\?|؟)", " ", q).strip()[:200] or q[:200]
            return self._tool(t, {"query": kw})

        # --- گیت ---
        if re.search(r"(گیت|git\s+(status|log|diff))", q, re.I) and (t := has("git")):
            if "log" in ql:
                return self._tool(t, {"action": "log"})
            if "diff" in ql:
                return self._tool(t, {"action": "diff"})
            return self._tool(t, {"action": "status"})

        # --- تودو ---
        if re.search(r"(تودو|وظایف|کارها|todo|task)", q, re.I) and (t := has("todo")):
            m2 = re.search(r"(?:اضافه کن|add)\s*[:：]?\s*(.+)", q, re.I | re.S)
            if m2:
                return self._tool(t, {"action": "add", "text": m2.group(1).strip()[:300]})
            return self._tool(t, {"action": "list"})

        # --- درخواست HTTP ---
        if re.search(r"(درخواست http|http request|api call|api بزن)", q, re.I) or (
            m and (t2 := has("http_request")) and re.search(r"(get|post)\s+https?://", q, re.I)
        ):
            m3 = re.search(r"(get|post)\s+(https?://[^\s]+)", q, re.I)
            if m3 and (t := has("http_request")):
                return self._tool(t, {"url": m3.group(2), "method": m3.group(1).upper()})

        # --- پرسش‌های اطلاعاتی (قبل از حدس ریاضی: فقط اگر فعل اقدام صریح نباشد) ---
        action_verbs = ("بنویس", "بخوان", "باز کن", "نمایش بده", "نشان بده", "بساز",
                        "ایجاد کن", "اجرا کن", "حساب کن", "محاسبه", "جستجو کن",
                        "سرچ کن", "پایتون", "python", "به خاطر بسپار", "یادت بماند",
                        "حذف کن", "پاک کن", "کپی کن", "منتقل کن", "ویرایش کن",
                        "لیست", "فهرست", "run", "write", "create", "read",
                        "تتر", "قیمت", "گوگل", "مرورگر", "سرچ", "اسکرین",
                        "تایپ", "کلیک", "بگو", "گوش", "توصیف", "کریپتو", "بیت")
        if not any(v in q for v in action_verbs):
            if re.search(r"(ساعت|تاریخ|امروز|چه روزی|time|date|today)", q) and (t := has("datetime_now")):
                return self._tool(t, {})
            if re.search(r"(سیستم|مشخصات|رم|cpu|حافظه|دیسک|sysinfo|system info)", q, re.I) and (t := has("sysinfo")):
                return self._tool(t, {})
            if re.search(r"(پردازش|پروسس|process|ps aux|تسک)", q, re.I) and (t := has("process_list")):
                return self._tool(t, {})

        # --- حدس آخر: الگوی «N op M چند می‌شود؟» ---
        m = re.search(r"([\d][\d\s+\-*/().^٪%×÷]*[\d])\s*(?:چند|حاصل|میشود|میشه|مساوی)", q)
        if m and m.group(1) and (t := has("calculator")):
            expr = m.group(1).strip().replace("×", "*").replace("÷", "/").replace("٪", "/100").replace("^", "**")
            if len(expr) >= 3:
                return self._tool(t, {"expression": expr})

        return None

    def _extract_path(self, q: str) -> Optional[str]:
        m = re.search(r"(?:در|از|path|in)\s+[«\"']?([./~][^\s«»\"']*)", q)
        if m:
            return m.group(1)
        m = re.search(r"[«\"']([./~][^«»\"']+)[»\"']", q)
        return m.group(1) if m else None

    def _summarize(self, q: str, tool_out: str) -> str:
        if not tool_out:
            return "انجام شد قربان. خروجی خاصی برنگشت."
        if len(tool_out) > 2500:
            tool_out = tool_out[:2500] + "\n…(کوتاه شد)"
        return f"انجام شد قربان. ✅\n\nنتیجه:\n{tool_out}"

    def _chat(self, q: str) -> str:
        ql = q.strip().lower()
        if re.match(r"^(سلام|درود|hi|hello)", ql):
            return ("سلام قربان. 👋 من **خورشید نهایی** هستم — ایجنت کامپیوتری شما.\n\n"
                    "می‌توانم فایل بسازم و بخوانم، دستور شل اجرا کنم، کد پایتون بنویسم و اجرا کنم، "
                    "در وب جست‌وجو کنم، حافظه دائمی داشته باشم و کارها را زمان‌بندی کنم.\n\n"
                    "بفرمایید چه کاری انجام دهم؟")
        if "اسمت" in q or "کی هستی" in q or "who are you" in ql:
            return ("من **خورشید نهایی (Ultimate Khorshid)** هستم — ایجنت کامپیوتری پایتونی، "
                    "الهام‌گرفته از OpenJarvis استنفورد. در حالت آفلاین (mock) اجرا می‌شوم؛ "
                    "برای مغز قدرتمندتر، یک موتور واقعی (Ollama یا OpenAI) وصل کنید.")
        if "چیکار" in q or "توانایی" in q or "abilities" in ql or "help" in ql or "راهنما" in q:
            return ("**توانایی‌های من:**\n"
                    "- 📁 فایل: خواندن/نوشتن/ویرایش/جست‌وجو/لیست\n"
                    "- 💻 شل: اجرای دستورات و اسکریپت پایتون\n"
                    "- 🌐 وب: جست‌وجو و خواندن صفحات + **مرورگر واقعی** (بگو «برو توی گوگل سرچ کن...»)\n"
                    "- 🖥️ دسکتاپ: اسکرین‌شات، موس، کیبورد، بینایی صفحه\n"
                    "- 💰 قیمت لحظه‌ای رمزارز (بگو «تتر چنده؟»)\n"
                    "- 🎙️ صدا: «بگو ...» می‌خوانم، «گوش بده» می‌شنوم\n"
                    "- 🧠 حافظه دائمی (SQLite)\n"
                    "- 📋 لیست کارها (todo) | 🗓 زمان‌بندی | 🔧 گیت\n\n"
                    "مثال: «برو توی گوگل سرچ کن تتر چنده» یا «از صفحه اسکرین‌شات بگیر»")
        return (f"متوجه شدم قربان. در حالت آفلاین هستم و پاسخ جامعی برای «{q[:80]}» ندارم.\n\n"
                "می‌توانید از من بخواهید فایل بخوانم/بنویسم، دستوری اجرا کنم، محاسبه کنم یا در وب جست‌وجو کنم.\n"
                "برای پاسخ‌های هوشمندتر، موتور Ollama یا OpenAI را فعال کنید (`khorshid doctor`).")
