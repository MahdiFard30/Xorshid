"""مدیریت Context — تخمین توکن، sliding window، بودجه per-agent.

- tiktoken اگر نصب بود دقیق؛ وگرنه هیوریستیک کاراکتری (فارسی ≈ ۳ کاراکتر/توکن).
- trim_messages: system نگه داشته می‌شود + دم پنجره لغزان + شمارش حذف‌شده‌ها.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

DEFAULT_BUDGET = 8000  # توکن ورودی پیش‌فرض هر فراخوانی
BUDGETS: Dict[str, int] = {
    "simple": 4000, "react": 6000, "computer": 12000, "researcher": 16000,
    "planner": 12000, "autonomous": 12000, "quiz": 8000, "supervisor": 16000,
}


def _has_tiktoken() -> bool:
    try:
        import importlib.util
        return importlib.util.find_spec("tiktoken") is not None
    except Exception:
        return False


def estimate_tokens(text: str, model: str = "") -> int:
    """تخمین تعداد توکن. دقیق با tiktoken، وگرنه هیوریستیک."""
    if not text:
        return 0
    if _has_tiktoken():
        try:
            import tiktoken  # type: ignore
            try:
                enc = tiktoken.encoding_for_model(model.split("/", 1)[-1] if "/" in model else "gpt-4o-mini")
            except Exception:
                enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            pass
    # هیوریستیک: فارسی/عربی ~۳، لاتین ~۴ کاراکتر در هر توکن
    fa = sum(1 for ch in text if "\u0600" <= ch <= "\u06FF")
    return max(1, fa // 3 + (len(text) - fa) // 4)


def messages_tokens(messages: List[Dict[str, Any]], model: str = "") -> int:
    return sum(estimate_tokens(str(m.get("content", "")), model) + 4 for m in messages)


def budget_for(agent_id: str, override: int = 0) -> int:
    if override and override > 0:
        return override
    return BUDGETS.get(agent_id or "", DEFAULT_BUDGET)


def trim_messages(messages: List[Dict[str, Any]], budget: int = DEFAULT_BUDGET,
                  model: str = "") -> Tuple[List[Dict[str, Any]], int, int]:
    """برش به بودجه: (پیام‌ها، تعداد حذف‌شده، توکن تخمینی).

    - پیام‌های system همیشه می‌مانند.
    - از انتها (جدیدترین) به‌اندازه بودجه نگه داشته می‌شود.
    - اگر هیچ پیام کاربری جا نشد، آخرین پیام کوتاه‌شده برمی‌گردد.
    """
    if not messages:
        return [], 0, 0
    systems = [m for m in messages if m.get("role") == "system"]
    rest = [m for m in messages if m.get("role") != "system"]
    sys_tok = messages_tokens(systems, model)
    kept: List[Dict[str, Any]] = []
    used = sys_tok
    for m in reversed(rest):
        t = estimate_tokens(str(m.get("content", "")), model) + 4
        if used + t > budget and kept:
            break
        kept.append(m)
        used += t
        if used >= budget:
            break
    kept.reverse()
    out = systems + kept
    dropped = len(messages) - len(out)
    if not kept and rest:  # بودجه خیلی کوچک: آخرین پیام را ببر
        last = dict(rest[-1])
        size = max(200, (budget - sys_tok) * 3)
        last["content"] = str(last.get("content", ""))[:size] + "…[trimmed]"
        out = systems + [last]
        dropped = len(messages) - len(out)
        used = messages_tokens(out, model)
    return out, dropped, used


def needs_summary(messages: List[Dict[str, Any]], budget: int = DEFAULT_BUDGET,
                  model: str = "") -> bool:
    return messages_tokens(messages, model) > budget * 2


def make_summarizer(engine: Any, model: str):
    """خلاصه‌ساز تدریجی تاریخچه با خود موتور (map-reduce ساده)."""
    def summarize(messages: List[Dict[str, Any]], keep_last: int = 6) -> List[Dict[str, Any]]:
        if len(messages) <= keep_last + 2:
            return messages
        old, tail = messages[:-(keep_last)], messages[-(keep_last):]
        convo = "\n".join(f"[{m.get('role')}]: {str(m.get('content', ''))[:800]}" for m in old)
        try:
            r = engine.generate(
                [{"role": "user", "content": "این گفت‌وگو را در ۱۰ خط فارسی خلاصه کن (نکات و تصمیم‌ها حفظ شود):\n" + convo[:6000]}],
                model, max_tokens=600)
            summary = str(r.get("content", ""))[:2000] or "(خلاصه نشد)"
        except Exception as e:
            summary = f"(خلاصه‌سازی نشد: {e})"
        return [{"role": "system", "content": f"[خلاصه گفت‌وگوی قبلی]\n{summary}"}] + tail
    return summarize
