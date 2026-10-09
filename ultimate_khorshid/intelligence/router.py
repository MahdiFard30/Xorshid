"""Heuristic router — انتخاب هوشمند ایجنت/مدل بر اساس نوع سؤال (مثل OpenJarvis)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List

from ultimate_khorshid.core.registry import RouterPolicyRegistry


@dataclass(slots=True)
class RoutingDecision:
    agent: str
    reason: str
    needs_tools: bool = True
    complexity: str = "medium"  # simple|medium|complex


_CODE_RE = re.compile(r"(کد|برنامه|پایتون|python|bug|error|traceback|فانکشن|کلاس|اسکریپت|sql|api)", re.I)
_COMPUTER_RE = re.compile(r"(فایل|فولدر|دایرکتوری|شل|ترمینال|اجرا کن|بساز|پاک کن|دانلود|نصب|گیت|git|سرور|file|folder|run|create|delete|install)", re.I)
_RESEARCH_RE = re.compile(r"(تحقیق|جستجو|مقاله|اخبار|مقایسه|بررسی کن|research|search|news|compare|آخرین|جدیدترین)", re.I)
_SIMPLE_RE = re.compile(r"^(سلام|درود|خداحافظ|ممنون|مرسی|تشکر|ok|hi|hello|thanks)\b", re.I)


@RouterPolicyRegistry.register("heuristic")
class HeuristicRouter:
    """روتر قاعده‌محور سبک و سریع."""

    def route(self, query: str, default_agent: str = "computer") -> RoutingDecision:
        q = query.strip()
        if _SIMPLE_RE.search(q) or len(q.split()) <= 3:
            return RoutingDecision(agent="simple", reason="گپ ساده — بدون ابزار", needs_tools=False, complexity="simple")
        if _RESEARCH_RE.search(q):
            return RoutingDecision(agent="researcher", reason="نیاز به جست‌وجوی چندمرحله‌ای", complexity="complex")
        if _CODE_RE.search(q) and ("اجرا" in q or "run" in q.lower() or "بنویس" in q):
            return RoutingDecision(agent="codeact", reason="کدنویسی + اجرا", complexity="complex")
        if _COMPUTER_RE.search(q):
            return RoutingDecision(agent="computer", reason="کار کامپیوتری (فایل/شل/سیستم)", complexity="medium")
        if len(q) > 400 or q.count("؟") + q.count("?") > 2:
            return RoutingDecision(agent="planner", reason="درخواست چندمرحله‌ای — نیاز به پلن", complexity="complex")
        return RoutingDecision(agent=default_agent, reason="پیش‌فرض", complexity="medium")

    def pick_tools(self, query: str, all_tools: List[str]) -> List[str]:
        """زیرمجموعه ابزار مرتبط (کاهش توکن و خطا)."""
        q = query.lower()
        if any(w in q for w in ("فایل", "file", "بخوان", "بنویس", "read", "write")):
            keep = {"file_read", "file_write", "file_edit", "file_list", "file_search", "think"}
        elif any(w in q for w in ("شل", "shell", "اجرا", "run", "نصب", "install", "دستور")):
            keep = {"shell_exec", "python_exec", "process_list", "think"}
        elif any(w in q for w in ("وب", "web", "search", "جستجو", "لینک", "سایت")):
            keep = {"web_search", "web_fetch", "http_request", "think"}
        else:
            return all_tools
        out = [t for t in all_tools if t in keep]
        return out or all_tools
