"""ابزارهای وب — web_search / web_fetch / http_request (فقط urllib)."""

from __future__ import annotations

import html
import json
import re
import urllib.parse
import urllib.request
from typing import Any

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

UA = {"User-Agent": "Mozilla/5.0 (UltimateKhorshid/1.0)"}


def _guard(text: str, source: str):
    """گارد تزریق محتوای خارجی؛ (متن، هشدارها)."""
    try:
        from ultimate_khorshid.security.injection import guard_text
        return guard_text(text, source)
    except Exception:
        return text, []


@ToolRegistry.register("web_search")
class WebSearchTool(BaseTool):
    tool_id = "web_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_search",
            description="جست‌وجوی وب (DuckDuckGo، بدون API key). خروجی: عنوان+لینک+خلاصه.",
            parameters={"type": "object", "properties": {
                "query": {"type": "string"}, "count": {"type": "integer"}},
                "required": ["query"]},
            category="web", timeout_seconds=35.0)

    def execute(self, **p: Any) -> ToolResult:
        q = str(p.get("query", "")).strip()
        count = min(max(int(p.get("count", 5) or 5), 1), 10)
        if not q:
            return ToolResult(tool_name="web_search", content="پرسش خالی است.", success=False)
        try:
            # ابتدا Instant Answer API
            url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
                {"q": q, "format": "json", "no_html": 1, "skip_disambig": 1})
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                data = json.loads(r.read().decode("utf-8", "replace"))
            out = []
            if data.get("AbstractText"):
                out.append(f"📌 {data.get('AbstractText')} ({data.get('AbstractURL','')})")
            for t in (data.get("RelatedTopics") or [])[:count]:
                if isinstance(t, dict) and t.get("Text"):
                    out.append(f"• {t['Text'][:220]} — {t.get('FirstURL','')}")
            # اگر خالی بود: html lite
            if not out:
                url2 = "https://lite.duckduckgo.com/lite/?" + urllib.parse.urlencode({"q": q})
                with urllib.request.urlopen(urllib.request.Request(url2, headers=UA), timeout=15) as r:
                    page = r.read().decode("utf-8", "replace")
                links = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', page, re.S)
                seen = set()
                for href, title in links:
                    title = re.sub(r"<[^>]+>", "", title).strip()
                    # لینک‌های lite ریدایرکت‌اند: //duckduckgo.com/l/?uddg=<url واقعی>
                    m_uddg = re.search(r"uddg=([^&\"']+)", href)
                    if m_uddg:
                        href = urllib.parse.unquote(m_uddg.group(1))
                    elif "duckduckgo.com" in href:
                        continue  # لینک ناوبری داخلی
                    if not title or len(title) < 10:
                        continue
                    if href.startswith("//"):
                        href = "https:" + href
                    if href in seen or not href.startswith("http"):
                        continue
                    seen.add(href)
                    out.append(f"• {html.unescape(title)[:200]} — {href[:200]}")
                    if len(out) >= count:
                        break
            if not out:
                return ToolResult(tool_name="web_search", content=f"نتیجه‌ای برای «{q}» پیدا نشد (ممکن است اینترنت قطع باشد).", success=False)
            body = f"🔍 نتایج «{q}»:\n" + "\n".join(out[:count])
            body, hits = _guard(body, "web_search")
            return ToolResult(tool_name="web_search", content=body,
                              metadata={"untrusted": True, "injection_hits": hits})
        except Exception as e:
            return ToolResult(tool_name="web_search", content=f"خطای جست‌وجو: {e}", success=False)


@ToolRegistry.register("web_fetch")
class WebFetchTool(BaseTool):
    tool_id = "web_fetch"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_fetch",
            description="خواندن متن یک صفحه وب (HTML تمیز می‌شود).",
            parameters={"type": "object", "properties": {
                "url": {"type": "string"}, "max_chars": {"type": "integer"}},
                "required": ["url"]},
            category="web", timeout_seconds=35.0)

    def execute(self, **p: Any) -> ToolResult:
        url = str(p.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            return ToolResult(tool_name="web_fetch", content="URL باید با http(s) شروع شود.", success=False)
        mx = min(max(int(p.get("max_chars", 6000) or 6000), 500), 20000)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
                raw = r.read(500_000).decode("utf-8", "replace")
            mt = re.search(r"<title[^>]*>(.*?)</title>", raw, re.S | re.I)
            title = re.sub(r"\s+", " ", html.unescape(mt.group(1))).strip() if mt else ""
            # حذف اسکریپت/استایل
            raw = re.sub(r"<script.*?</script>", " ", raw, flags=re.S | re.I)
            raw = re.sub(r"<style.*?</style>", " ", raw, flags=re.S | re.I)
            raw = re.sub(r"<[^>]+>", " ", raw)
            text = re.sub(r"\s+", " ", html.unescape(raw)).strip()
            if len(text) > mx:
                text = text[:mx] + "…"
            head = f"🌐 {title}\n{url}" if title else f"🌐 {url}"
            body, hits = _guard(f"{head}\n\n{text or '(متن خالی)'}", "web_fetch")
            return ToolResult(tool_name="web_fetch", content=body,
                              metadata={"untrusted": True, "injection_hits": hits})
        except Exception as e:
            return ToolResult(tool_name="web_fetch", content=f"خطا در خواندن صفحه: {e}", success=False)


@ToolRegistry.register("http_request")
class HttpRequestTool(BaseTool):
    tool_id = "http_request"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="http_request",
            description="درخواست HTTP خام (GET/POST/PUT/DELETE) برای کار با APIها.",
            parameters={"type": "object", "properties": {
                "url": {"type": "string"}, "method": {"type": "string"},
                "headers": {"type": "object"}, "body": {"type": "string"}},
                "required": ["url"]},
            category="web", timeout_seconds=35.0)

    def execute(self, **p: Any) -> ToolResult:
        url = str(p.get("url", "")).strip()
        method = str(p.get("method", "GET") or "GET").upper()
        headers = dict(p.get("headers", {}) or {})
        headers.setdefault("User-Agent", UA["User-Agent"])
        body = p.get("body")
        data = body.encode("utf-8") if isinstance(body, str) and body else None
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=20) as r:
                content = r.read(100_000).decode("utf-8", "replace")
            if len(content) > 8000:
                content = content[:8000] + "…"
            return ToolResult(tool_name="http_request", content=f"{method} {url}\n\n{content}")
        except Exception as e:
            return ToolResult(tool_name="http_request", content=f"خطا: {e}", success=False)


@ToolRegistry.register("web_fetch_many")
class WebFetchManyTool(BaseTool):
    tool_id = "web_fetch_many"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="web_fetch_many",
            description="خواندن موازی چند URL (تا ۵ عدد) در یک فراخوانی.",
            parameters={"type": "object", "properties": {
                "urls": {"type": "array", "items": {"type": "string"}},
                "max_chars": {"type": "integer"}}, "required": ["urls"]},
            category="web", timeout_seconds=60.0)

    def execute(self, **p: Any) -> ToolResult:
        from ultimate_khorshid.core.parallel import run_parallel
        urls = [str(u).strip() for u in (p.get("urls") or [])][:5]
        mx = int(p.get("max_chars", 3000) or 3000)
        if not urls:
            return ToolResult(tool_name="web_fetch_many", content="URLای داده نشد.",
                              success=False)
        one = WebFetchTool()
        res = run_parallel({u: (lambda u=u: one.execute(url=u, max_chars=mx))
                            for u in urls}, timeout=55.0)
        parts = []
        for u in urls:
            ok, r = res[u]
            if ok and r.success:
                parts.append(f"━━━ ✅ {u}\n{r.content[:mx]}")
            else:
                err = r.content[:200] if ok else str(r)[:200]
                parts.append(f"━━━ ❌ {u}\n{err}")
        return ToolResult(tool_name="web_fetch_many", content="\n\n".join(parts),
                          success=any(ok and r.success for ok, r in res.values()),
                          metadata={"untrusted": True, "failed_urls": [u for u in urls if not res[u][0] or not res[u][1].success]})
