"""مرورگر واقعی با Playwright — باز کردن سایت، جست‌وجوی گوگل، کلیک، تایپ، خواندن.

نصب:
  pip install playwright && playwright install chromium
  # یا: pip install -e ".[browser]" && playwright install chromium
"""

from __future__ import annotations

from typing import Any, Dict, List
from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

BROWSER_PIP = 'pip install playwright && playwright install chromium'

_state: Dict[str, Any] = {"pw": None, "browser": None, "page": None}
_elements: List[Any] = []  # عناصر تعاملی آخرین snapshot


def _need() -> str | None:
    import importlib.util
    try:
        has = importlib.util.find_spec("playwright") is not None
    except Exception:
        has = False
    if not has:
        return f"Playwright نصب نیست. نصب:\n  {BROWSER_PIP}"
    return None


def _page(headless: bool = False):
    from playwright.sync_api import sync_playwright  # type: ignore
    if _state["page"] is not None:
        try:
            if not _state["page"].is_closed() and _state["browser"].is_connected():
                return _state["page"]
        except Exception:
            pass
    close_browser()
    pw = sync_playwright().start()
    try:
        browser = pw.chromium.launch(headless=headless)
        page = browser.new_page(viewport={"width": 1366, "height": 900})
    except Exception:
        pw.stop()
        raise
    _state.update(pw=pw, browser=browser, page=page)
    return page


def close_browser() -> None:
    try:
        if _state["browser"]:
            _state["browser"].close()
    except Exception:
        pass
    try:
        if _state["pw"]:
            _state["pw"].stop()
    except Exception:
        pass
    _state.update(pw=None, browser=None, page=None)
    _elements.clear()


def _collect() -> List[Dict[str, str]]:
    """گردآوری عناصر تعاملی با ایندکس."""
    global _elements
    page = _state["page"]
    out: List[Dict[str, str]] = []
    _elements = []
    try:
        els = page.query_selector_all(
            "a, button, input, textarea, select, [role=button], [role=link], [role=tab]")
    except Exception:
        return out
    for el in els[:120]:
        try:
            if not el.is_visible():
                continue
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            txt = (el.inner_text(timeout=500) or "").strip().replace("\n", " ")[:80]
            ph = el.get_attribute("placeholder") or ""
            name = el.get_attribute("name") or ""
            label = txt or ph or name or f"<{tag}>"
            _elements.append(el)
            out.append({"i": str(len(_elements) - 1), "tag": tag, "label": label})
        except Exception:
            continue
    return out


def _by_ref(ref: str):
    if ref.isdigit() and int(ref) < len(_elements):
        return _elements[int(ref)]
    return None


# ------------------------------------------------------------- ابزارها ---

@ToolRegistry.register("browser_open")
class BrowserOpenTool(BaseTool):
    tool_id = "browser_open"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_open", description="باز کردن یک آدرس در مرورگر واقعی.",
            parameters={"type": "object", "properties": {
                "url": {"type": "string"},
                "headless": {"type": "boolean", "description": "پیش‌فرض false (پنجره قابل مشاهده)"}},
                "required": ["url"]}, category="browser", timeout_seconds=60.0)

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_open", content=e, success=False)
        url = str(p.get("url", "")).strip()
        if not url.startswith("http"):
            url = "https://" + url
        try:
            page = _page(headless=bool(p.get("headless", False)))
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            _elements.clear()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            return ToolResult(tool_name="browser_open",
                              content=f"🌐 باز شد: {page.title()[:120]}\nURL: {page.url}")
        except Exception as ex:
            return ToolResult(tool_name="browser_open", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_snapshot")
class BrowserSnapshotTool(BaseTool):
    tool_id = "browser_snapshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_snapshot",
            description="لیست عناصر قابل کلیک/تایپ صفحه با ایندکس (برای browser_click/type).",
            parameters={"type": "object", "properties": {}}, category="browser")

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_snapshot", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_snapshot",
                              content="مرورگر باز نیست؛ اول browser_open.", success=False)
        els = _collect()
        if not els:
            return ToolResult(tool_name="browser_snapshot", content="(عنصر تعاملی پیدا نشد)")
        lines = [f"[{x['i']}] <{x['tag']}> {x['label']}" for x in els[:80]]
        return ToolResult(tool_name="browser_snapshot",
                          content=f"🧭 {_state['page'].url}\n" + "\n".join(lines))


@ToolRegistry.register("browser_click")
class BrowserClickTool(BaseTool):
    tool_id = "browser_click"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_click", description="کلیک روی عنصر (ایندکس snapshot یا متن لینک/دکمه).",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "ایندکس عددی یا متن"},
                "by": {"type": "string", "description": "index|text (پیش‌فرض index)"}},
                "required": ["ref"]}, category="browser", timeout_seconds=30.0)

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_click", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_click", content="مرورگر باز نیست.", success=False)
        ref, by = str(p.get("ref", "")), str(p.get("by", "index"))
        try:
            if by == "text":
                _state["page"].get_by_text(ref, exact=False).first.click(timeout=10000)
            else:
                el = _by_ref(ref)
                if el is None:
                    return ToolResult(tool_name="browser_click",
                                      content=f"ایندکس {ref} معتبر نیست؛ browser_snapshot بگیر.", success=False)
                el.click(timeout=10000)
            return ToolResult(tool_name="browser_click", content=f"🖱️ کلیک شد: {ref}")
        except Exception as ex:
            return ToolResult(tool_name="browser_click", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_type")
class BrowserTypeTool(BaseTool):
    tool_id = "browser_type"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_type", description="تایپ متن در فیلد (ایندکس، سلکتور css:، یا placeholder:).",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string"}, "text": {"type": "string"},
                "submit": {"type": "boolean", "description": "زدن Enter بعد از تایپ"}},
                "required": ["ref", "text"]}, category="browser", timeout_seconds=30.0)

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_type", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_type", content="مرورگر باز نیست.", success=False)
        ref, text = str(p.get("ref", "")), str(p.get("text", ""))
        try:
            page = _state["page"]
            if ref.startswith("css:"):
                page.locator(ref[4:]).first.fill(text, timeout=10000)
            elif ref.startswith("placeholder:"):
                page.get_by_placeholder(ref[12:]).first.fill(text, timeout=10000)
            else:
                el = _by_ref(ref)
                if el is None:
                    return ToolResult(tool_name="browser_type",
                                      content=f"ایندکس {ref} معتبر نیست.", success=False)
                el.fill(text, timeout=10000)
            if p.get("submit"):
                page.keyboard.press("Enter")
                page.wait_for_load_state("domcontentloaded", timeout=15000)
            return ToolResult(tool_name="browser_type", content=f"⌨️ تایپ شد در {ref}")
        except Exception as ex:
            return ToolResult(tool_name="browser_type", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_press")
class BrowserPressTool(BaseTool):
    tool_id = "browser_press"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_press", description="زدن کلید در مرورگر (Enter, Escape, Tab...).",
            parameters={"type": "object", "properties": {"key": {"type": "string"}}},
            category="browser")

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_press", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_press", content="مرورگر باز نیست.", success=False)
        try:
            _state["page"].keyboard.press(str(p.get("key", "Enter")))
            return ToolResult(tool_name="browser_press", content=f"⌨️ {p.get('key')} زده شد.")
        except Exception as ex:
            return ToolResult(tool_name="browser_press", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_text")
class BrowserTextTool(BaseTool):
    tool_id = "browser_text"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_text", description="خواندن متن قابل مشاهده صفحه.",
            parameters={"type": "object", "properties": {
                "max_chars": {"type": "integer"}}}, category="browser")

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_text", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_text", content="مرورگر باز نیست.", success=False)
        try:
            txt = _state["page"].inner_text("body", timeout=10000) or ""
            mx = min(max(int(p.get("max_chars", 6000) or 6000), 500), 15000)
            return ToolResult(tool_name="browser_text",
                              content=f"📄 { _state['page'].url}\n\n{txt[:mx]}")
        except Exception as ex:
            return ToolResult(tool_name="browser_text", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_screenshot")
class BrowserScreenshotTool(BaseTool):
    tool_id = "browser_screenshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_screenshot", description="عکس از صفحه مرورگر.",
            parameters={"type": "object", "properties": {}}, category="browser")

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_screenshot", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_screenshot", content="مرورگر باز نیست.", success=False)
        try:
            from ultimate_khorshid.tools.desktop import shots_dir
            from datetime import datetime
            fp = str(shots_dir() / f"browser_{datetime.now():%Y%m%d_%H%M%S}.png")
            _state["page"].screenshot(path=fp)
            return ToolResult(tool_name="browser_screenshot", content=f"📸 {fp}")
        except Exception as ex:
            return ToolResult(tool_name="browser_screenshot", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_google_search")
class BrowserGoogleSearchTool(BaseTool):
    tool_id = "browser_google_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_google_search",
            description="جست‌وجوی واقعی در گوگل با مرورگر (باز کردن گوگل + تایپ + خواندن نتایج).",
            parameters={"type": "object", "properties": {
                "query": {"type": "string"},
                "headless": {"type": "boolean"}}, "required": ["query"]},
            category="browser", timeout_seconds=90.0)

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_google_search", content=e, success=False)
        q = str(p.get("query", "")).strip()
        try:
            page = _page(headless=bool(p.get("headless", False)))
            page.goto("https://www.google.com", timeout=30000, wait_until="domcontentloaded")
            _elements.clear()
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            box = page.locator('textarea[name="q"], input[name="q"]').first
            box.fill(q, timeout=10000)
            box.press("Enter")
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            page.wait_for_timeout(1500)
            txt = page.inner_text("body", timeout=10000) or ""
            # استخراج لینک‌های نتایج
            links = []
            for a in page.query_selector_all("a h3"):
                try:
                    t = (a.inner_text(timeout=500) or "").strip()[:120]
                    href = a.evaluate("h => h.closest('a')?.href || ''")
                    if t and href and "google.com" not in href:
                        links.append(f"• {t} — {href[:150]}")
                    if len(links) >= 8:
                        break
                except Exception:
                    continue
            body = "🔗 نتایج:\n" + "\n".join(links) if links else txt[:4000]
            return ToolResult(tool_name="browser_google_search",
                              content=f"🔍 گوگل: «{q}»\n\n{body[:5000]}")
        except Exception as ex:
            return ToolResult(tool_name="browser_google_search",
                              content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_close")
class BrowserCloseTool(BaseTool):
    tool_id = "browser_close"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_close", description="بستن مرورگر.",
            parameters={"type": "object", "properties": {}}, category="browser")

    def execute(self, **p: Any) -> ToolResult:
        close_browser()
        return ToolResult(tool_name="browser_close", content="🌐 مرورگر بسته شد.")


def _labeled_forms() -> List[Dict[str, Any]]:
    """استخراج فرم‌ها با لیبل: text/radio/checkbox/select/textarea."""
    page = _state["page"]
    out: List[Dict[str, Any]] = []
    try:
        els = page.query_selector_all("input, textarea, select")
    except Exception:
        return out
    for el in els[:150]:
        try:
            if not el.is_visible():
                continue
            tag = el.evaluate("e => e.tagName.toLowerCase()")
            typ = (el.get_attribute("type") or "").lower() if tag == "input" else tag
            if typ in ("hidden", "submit", "button", "image"):
                continue
            label = el.evaluate("""e => {
                const id = e.id ? document.querySelector(`label[for="${e.id}"]`) : null;
                const wrap = e.closest('label');
                const aria = e.getAttribute('aria-label') || '';
                const ph = e.getAttribute('placeholder') || '';
                const name = e.getAttribute('name') || '';
                const val = (e.value || '').slice(0, 60);
                let txt = (id ? id.innerText : '') || (wrap ? wrap.innerText : '') || aria || ph || name || val;
                return (txt || '').trim().replace(/\\s+/g, ' ').slice(0, 150);
            }""") or ""
            item: Dict[str, Any] = {"tag": tag, "type": typ, "label": label}
            if tag == "select":
                try:
                    opts = el.query_selector_all("option")
                    item["options"] = [((o.inner_text(timeout=300) or "").strip()[:60]) for o in opts[:30]]
                except Exception:
                    item["options"] = []
            if typ in ("radio", "checkbox"):
                try:
                    item["checked"] = el.is_checked()
                    item["value"] = el.get_attribute("value") or ""
                except Exception:
                    pass
            _elements.append(el)
            item["i"] = str(len(_elements) - 1)
            out.append(item)
        except Exception:
            continue
    return out


@ToolRegistry.register("browser_forms")
class BrowserFormsTool(BaseTool):
    tool_id = "browser_forms"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_forms",
            description="استخراج همه فیلدهای فرم صفحه (متن/تستی/چک‌باکس/دراپ‌داون) با لیبل و ایندکس. قدم اول حل آزمون.",
            parameters={"type": "object", "properties": {}}, category="browser")

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_forms", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_forms", content="مرورگر باز نیست.", success=False)
        global _elements
        _elements = []
        forms = _labeled_forms()
        if not forms:
            return ToolResult(tool_name="browser_forms", content="(فرمی در صفحه پیدا نشد)")
        lines = []
        for f in forms:
            extra = ""
            if f.get("options"):
                extra = " | گزینه‌ها: " + "، ".join(f["options"][:10])
            if f["type"] in ("radio", "checkbox"):
                extra = f" [{'✓' if f.get('checked') else ' '}] value={f.get('value','')}"
            lines.append(f"[{f['i']}] ({f['type']}) {f['label'] or '(بی‌نام)'}{extra}")
        return ToolResult(tool_name="browser_forms",
                          content=f"📝 {len(forms)} فیلد در {_state['page'].url}:\n" + "\n".join(lines[:100]))


@ToolRegistry.register("browser_check")
class BrowserCheckTool(BaseTool):
    tool_id = "browser_check"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_check",
            description="تیک زدن رادیو/چک‌باکس با ایندکس (از browser_forms) یا متن لیبل.",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "ایندکس یا متن لیبل"},
                "uncheck": {"type": "boolean"}}, "required": ["ref"]},
            category="browser", timeout_seconds=30.0)

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_check", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_check", content="مرورگر باز نیست.", success=False)
        ref = str(p.get("ref", ""))
        try:
            page = _state["page"]
            el = _by_ref(ref) if ref.isdigit() else None
            if el is None and ref:
                el = page.get_by_label(ref, exact=False).first
            if el is None:
                return ToolResult(tool_name="browser_check",
                                  content=f"عنصر {ref} پیدا نشد.", success=False)
            if p.get("uncheck"):
                el.uncheck(timeout=8000)
            else:
                el.check(timeout=8000)
            return ToolResult(tool_name="browser_check",
                              content=f"☑️ {'برداشته شد' if p.get('uncheck') else 'انتخاب شد'}: {ref}")
        except Exception as ex:
            return ToolResult(tool_name="browser_check", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_select_option")
class BrowserSelectOptionTool(BaseTool):
    tool_id = "browser_select_option"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_select_option",
            description="انتخاب گزینه از دراپ‌داون (select) با ایندکس + متن/مقدار گزینه.",
            parameters={"type": "object", "properties": {
                "ref": {"type": "string", "description": "ایندکس از browser_forms"},
                "option": {"type": "string", "description": "متن یا value گزینه"}},
                "required": ["ref", "option"]},
            category="browser", timeout_seconds=30.0)

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_select_option", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_select_option", content="مرورگر باز نیست.", success=False)
        try:
            el = _by_ref(str(p.get("ref", "")))
            if el is None:
                return ToolResult(tool_name="browser_select_option",
                                  content="ایندکس معتبر نیست.", success=False)
            opt = str(p.get("option", ""))
            try:
                el.select_option(label=opt, timeout=8000)
            except Exception:
                el.select_option(value=opt, timeout=8000)
            return ToolResult(tool_name="browser_select_option",
                              content=f"🔽 انتخاب شد: {opt}")
        except Exception as ex:
            return ToolResult(tool_name="browser_select_option", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_a11y")
class BrowserA11yTool(BaseTool):
    tool_id = "browser_a11y"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_a11y",
            description="درخت دسترسی‌پذیری (a11y) صفحه: نقش/نام عناصر برای فهم دقیق ساختار.",
            parameters={"type": "object", "properties": {
                "max_nodes": {"type": "integer", "description": "سقف گره (پیش‌فرض ۸۰)"}},
                "required": []},
            category="browser", timeout_seconds=30.0)

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_a11y", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_a11y", content="مرورگر باز نیست.", success=False)
        try:
            page = _state["page"]
            locator = page.locator("body")
            modern = getattr(locator, "aria_snapshot", None)
            snap = {} if callable(modern) else (page.accessibility.snapshot() or {})
            lines: List[str] = []

            def walk(node: Any, depth: int) -> None:
                if len(lines) >= mx or not isinstance(node, dict):
                    return
                role, name = node.get("role", ""), (node.get("name") or "").strip()
                if role not in ("generic", "none", "") or name:
                    lines.append("  " * min(depth, 6) + f"{role}: {name[:80]}".strip())
                for ch in node.get("children") or []:
                    walk(ch, depth + 1)

            mx = min(max(int(p.get("max_nodes", 80) or 80), 10), 300)
            if callable(modern):
                lines = modern(timeout=15000).splitlines()
            else:
                walk(snap, 0)
            body = "\n".join(lines[:mx]) or "(درخت خالی)"
            try:
                from ultimate_khorshid.security.injection import guard_text
                body, hits = guard_text(body, "browser_a11y")
            except Exception:
                hits = []
            return ToolResult(tool_name="browser_a11y",
                              content=f"♿ درخت دسترسی‌پذیری:\n{body}",
                              metadata={"untrusted": True, "injection_hits": hits})
        except Exception as ex:
            return ToolResult(tool_name="browser_a11y", content=f"خطا: {ex}", success=False)


@ToolRegistry.register("browser_wait")
class BrowserWaitTool(BaseTool):
    tool_id = "browser_wait"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="browser_wait",
            description="انتظار هوشمند: سلکتور/متن/لود کامل (برای SPAها).",
            parameters={"type": "object", "properties": {
                "selector": {"type": "string", "description": "سلکتور CSS"},
                "text": {"type": "string", "description": "متنی که باید ظاهر شود"},
                "state": {"type": "string", "description": "load|domcontentloaded|networkidle"},
                "timeout": {"type": "integer", "description": "میلی‌ثانیه (پیش‌فرض ۱۵۰۰۰)"}},
                "required": []},
            category="browser", timeout_seconds=40.0)

    def execute(self, **p: Any) -> ToolResult:
        if (e := _need()):
            return ToolResult(tool_name="browser_wait", content=e, success=False)
        if _state["page"] is None:
            return ToolResult(tool_name="browser_wait", content="مرورگر باز نیست.", success=False)
        tmo = min(max(int(p.get("timeout", 15000) or 15000), 500), 60000)
        try:
            pg = _state["page"]
            if p.get("selector"):
                pg.wait_for_selector(str(p["selector"]), timeout=tmo)
                return ToolResult(tool_name="browser_wait",
                                  content=f"⏳ سلکتور ظاهر شد: {p['selector']}")
            if p.get("text"):
                pg.get_by_text(str(p["text"])).first.wait_for(timeout=tmo)
                return ToolResult(tool_name="browser_wait",
                                  content=f"⏳ متن ظاهر شد: {p['text']}")
            pg.wait_for_load_state(str(p.get("state", "domcontentloaded") or "domcontentloaded"),
                                   timeout=tmo)
            return ToolResult(tool_name="browser_wait", content="⏳ صفحه لود شد.")
        except Exception as ex:
            return ToolResult(tool_name="browser_wait",
                              content=f"⏳ انتظار تمام شد: {ex}", success=False)
