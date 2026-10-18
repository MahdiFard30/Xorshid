"""مرورگر واقعی با Playwright — باز کردن سایت، جست‌وجوی گوگل، کلیک، تایپ، خواندن.

نصب:
  pip install playwright && playwright install chromium
  # یا: pip install -e ".[browser]" && playwright install chromium
"""

from __future__ import annotations

from typing import Any, Dict, List
from pathlib import Path
import shutil
import atexit
import socket
import subprocess
import time
from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

BROWSER_PIP = 'pip install playwright && playwright install chromium'

_PROFILE_ROOT = Path(__file__).resolve().parents[2] / '.khorshid-browser'
_state: Dict[str, Any] = {"pw": None, "browser": None, "context": None,
                          "page": None, "media_page": None, "process": None}
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


def _chrome_executable():
    return (shutil.which('google-chrome') or shutil.which('google-chrome-stable') or
            ('/opt/google/chrome/chrome' if Path('/opt/google/chrome/chrome').is_file() else None))


def _stop_process(process):
    """Only terminate the Chrome process created by this module."""
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def _stop_owned_chrome():
    _stop_process(_state.get('process'))


atexit.register(_stop_owned_chrome)


def _launch_chrome(pw, executable, profile, headless):
    # Normal Chrome startup preserves its media/network defaults. CDP provides
    # control without Playwright's automation launch flags. Localhost only.
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    args = [executable, f'--user-data-dir={profile}', f'--remote-debugging-port={port}',
            '--remote-debugging-address=127.0.0.1', '--no-first-run',
            '--no-default-browser-check', '--window-size=1366,900']
    if headless:
        args.append('--headless=new')
    args.append('about:blank')
    process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError('Chrome باز نشد؛ شاید پروفایل خورشید در اجرای دیگری باز باشد.')
            try:
                browser = pw.chromium.connect_over_cdp(f'http://127.0.0.1:{port}', timeout=1000)
                return browser, browser.contexts[0], process
            except Exception:
                time.sleep(0.15)
        raise RuntimeError('اتصال کنترلی به Chrome برقرار نشد.')
    except Exception:
        _stop_process(process)
        raise


def _page(headless: bool = False):
    from playwright.sync_api import sync_playwright  # type: ignore
    if _state["context"] is not None:
        try:
            if _state["browser"].is_connected():
                if _state["page"] is None or _state["page"].is_closed():
                    _state["page"] = _state["context"].new_page()
                return _state["page"]
        except Exception:
            pass
    close_browser()
    pw = sync_playwright().start()
    try:
        # Keep consent/login between restarts; never use the user's main profile.
        chrome = _chrome_executable()
        profile = _PROFILE_ROOT / ('chrome' if chrome else 'chromium')
        profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        _PROFILE_ROOT.chmod(0o700)
        profile.chmod(0o700)
        process = None
        if chrome:
            browser, context, process = _launch_chrome(pw, chrome, profile, headless)
        else:
            context = pw.chromium.launch_persistent_context(
                str(profile), headless=headless, viewport={"width": 1366, "height": 900})
            browser = context.browser
        page = context.pages[0] if context.pages else context.new_page()
    except Exception:
        _stop_process(locals().get('process'))
        pw.stop()
        raise
    _state.update(pw=pw, browser=browser, context=context, page=page, media_page=None, process=process)
    return page


def close_browser() -> None:
    try:
        if _state['process'] is not None and _state['browser'] is not None:
            _state['browser'].new_browser_cdp_session().send('Browser.close')
        elif _state["context"]:
            _state["context"].close()
        elif _state["browser"]:
            _state["browser"].close()
    except Exception:
        pass
    process = _state.get('process')
    if process is not None:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _stop_process(process)
    try:
        if _state["pw"]:
            _state["pw"].stop()
    except Exception:
        pass
    _state.update(pw=None, browser=None, context=None, page=None, media_page=None, process=None)
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


# ------------------------------------------------------------- YouTube ---
def _youtube_text(text):
    import re
    table=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')
    text=text.lower().translate(table).replace('ي','ی').replace('ك','ک').replace('\u200c',' ')
    text=text.replace('paaytakht','پایتخت').replace('paytakht','پایتخت')
    text=re.sub(r'(?<=[^\W\d_])(?=\d)|(?<=\d)(?=[^\W\d_])',' ',text)
    numbers={'اول':1,'اولو':1,'اولین':1,'یک':1,'یکم':1,'دوم':2,'دو':2,'سوم':3,'سه':3,
             'چهارم':4,'چهار':4,'پنجم':5,'پنج':5,'ششم':6,'شش':6,'هفتم':7,'هفت':7,
             'هشتم':8,'هشت':8,'نهم':9,'نه':9,'دهم':10,'ده':10}
    return ' '.join(str(numbers.get(word,word)) for word in re.findall(r'\w+',text))


def _youtube_episode(text):
    import re
    match=re.search(r'(?:^|\s)(?:قسمت|episode|ep|e)\s*(\d+)\b',_youtube_text(text))
    return int(match.group(1)) if match else None


def choose_youtube_result(query,results):
    """Use visible titles, never confuse a different episode with the request."""
    import re
    from urllib.parse import urlparse,parse_qs
    wanted=_youtube_text(query)
    episode=_youtube_episode(query)
    season=re.search(r'پایتخت\s+(\d+)',wanted)
    fillers={'قسمت','سریال','فیلم','ویدیو','ویدئو','پخش','کامل','یوتیوب','youtube','episode','ep','season','فصل'}
    subjects={word for word in wanted.split() if not word.isdigit() and word not in fillers}
    for item in results:
        url=urlparse(item['url'])
        if url.scheme!='https' or url.hostname not in ('www.youtube.com','youtube.com') or url.path!='/watch' or not parse_qs(url.query).get('v'):
            continue
        title=_youtube_text(item['title'])
        if episode is not None and _youtube_episode(item['title'])!=episode:
            continue
        if season and not re.search(r'پایتخت\s+0*'+season.group(1)+r'\b',title):
            continue
        if subjects and not subjects.intersection(title.split()):
            continue
        return item
    return None


def _youtube_consent(page):
    """Dismiss only YouTube's consent, without enabling optional tracking."""
    import re
    from urllib.parse import urlsplit
    if urlsplit(page.url).hostname not in {'youtube.com', 'www.youtube.com', 'consent.youtube.com'}:
        return
    reject = page.get_by_role('button', name=re.compile(
        r'^(Reject all|رد همه|رد کردن همه|Avvisa alla|Alle ablehnen|Tout refuser)$', re.I))
    if reject.count() and reject.first.is_visible():
        reject.first.click(timeout=5000)
        page.wait_for_load_state('domcontentloaded', timeout=15000)


def _youtube_state(page):
    return page.evaluate('''()=>{const v=document.querySelector('video');
        const error=document.querySelector('.ytp-error-content-wrap');
        return {playing:!!v&&!v.paused&&!v.ended&&v.currentTime>0,
            advertisement:!!document.querySelector('.html5-video-player.ad-showing'),
            current_time:v?v.currentTime:0, ready_state:v?v.readyState:0,
            volume:v?Math.round(v.volume*100):null, muted:v?!!v.muted:null,
            media_error:v&&v.error?v.error.code:null,
            player_error:error&&error.getClientRects().length?error.innerText.slice(0,400):'',
            title:document.title, url:location.href};}''')


@ToolRegistry.register('youtube_play')
class YouTubePlayTool(BaseTool):
    tool_id='youtube_play'

    @property
    def spec(self):
        return ToolSpec(name=self.tool_id,category='browser',timeout_seconds=100,
            description='جست‌وجو و پخش ویدیوی یوتیوب در مرورگر قابل مشاهده. برای سریال نام، فصل و قسمت را در query بگذار؛ ارجاع پیام کوتاه را از گفتگو کامل کن. خودش ویدیو را انتخاب می‌کند؛ playing=true تأیید پخش است، صرف بازشدن صفحه تأیید پخش نیست.',
            parameters={'type':'object','properties':{'query':{'type':'string','minLength':1}},'required':['query']})

    def execute(self,**p):
        import re
        from urllib.parse import urlencode,urljoin
        if (error:=_need()):
            return ToolResult(tool_name=self.tool_id,content=error,success=False)
        query=str(p.get('query','')).strip()
        if not query or len(query)>500:
            return ToolResult(tool_name=self.tool_id,content='نام ویدیوی قابل جست‌وجو لازم است.',success=False)
        selected=None
        try:
            page=_page(headless=False)
            page.goto('https://www.youtube.com/results?'+urlencode({'search_query':query}),
                      wait_until='domcontentloaded',timeout=30000)
            _elements.clear()
            _youtube_consent(page)
            links=page.locator('ytd-video-renderer a#video-title[href*="/watch?"]')
            links.first.wait_for(state='visible',timeout=15000)
            results=[]
            for index in range(min(links.count(),20)):
                link=links.nth(index)
                title=(link.get_attribute('title') or link.inner_text()).strip()
                href=link.get_attribute('href') or ''
                results.append({'title':title,'url':urljoin('https://www.youtube.com',href),'index':index})
            selected=choose_youtube_result(query,results)
            if selected is None:
                return ToolResult(tool_name=self.tool_id,success=False,
                    content='ویدیویی با عنوان و شمارهٔ قسمت مطابق درخواست پیدا نشد؛ ویدیوی دیگری پخش نشد.',
                    metadata={'playing':False,'results':results[:8]})
            links.nth(selected['index']).click(timeout=10000)
            _state['media_page']=page
            page.wait_for_load_state('domcontentloaded',timeout=15000)
            video=page.locator('video').first
            video.wait_for(state='attached',timeout=10000)
            button=page.locator('button.ytp-large-play-button').first
            if button.count() and button.is_visible():
                button.click(timeout=3000)
            else:
                video.evaluate('(v)=>Promise.race([v.play().then(()=>true).catch(()=>false),new Promise(resolve=>setTimeout(()=>resolve(false),3000))])')
            try:
                page.wait_for_function('()=>{const v=document.querySelector("video");return v&&!v.paused&&v.currentTime>0;}',timeout=10000)
            except Exception:
                pass
            state=_youtube_state(page)
            playing=(bool(state.get('playing')) and not state.get('advertisement')
                     and not state.get('player_error') and not state.get('media_error'))
            note=('ویدیو در حال پخش است: ' if playing else
                  'صفحهٔ ویدیو باز شد، اما پخش قسمت هنوز تأیید نشده است: ')+selected['title']
            if state.get('advertisement'):
                note+=' (فعلاً تبلیغ پخش می‌شود.)'
            if state.get('player_error') or state.get('media_error'):
                note+=' خطای پخش: '+str(state.get('player_error') or state['media_error'])
            return ToolResult(tool_name=self.tool_id,content=note,
                success=not bool(state.get('player_error') or state.get('media_error')),
                metadata={**state,'playing':playing,'advertisement':bool(state.get('advertisement')),
                          'title':selected['title'],'url':selected['url']})
        except Exception as exc:
            return ToolResult(tool_name=self.tool_id,success=False,
                content='پخش یوتیوب تأیید نشد: '+str(exc)[:350],
                metadata={'playing':False,'selected':selected})


@ToolRegistry.register('youtube_control')
class YouTubeControlTool(BaseTool):
    tool_id='youtube_control'

    @property
    def spec(self):
        return ToolSpec(name=self.tool_id, category='browser', timeout_seconds=25,
            description='کنترل ویدیوی یوتیوب: وضعیت، مکث، ادامه، بعدی، بستن تب، کم/زیاد کردن صدا، قطع/وصل صدا و تنظیم درصد صدا. برای قسمت بعدی سریال از youtube_play استفاده کن.',
            parameters={'type':'object','properties':{'action':{'type':'string',
                'enum':['status','pause','resume','next','close','volume_down','volume_up','mute','unmute','set_volume']},
                'volume':{'type':'integer','minimum':0,'maximum':100,'description':'درصد صدا برای set_volume'},
                'step':{'type':'integer','minimum':1,'maximum':100,'description':'میزان تغییر صدا؛ پیش‌فرض ۱۵ درصد'}},'required':['action']})

    def execute(self, **p):
        from urllib.parse import urlsplit
        action=p.get('action')
        volume_actions={'volume_down','volume_up','mute','unmute','set_volume'}
        if action not in {'status','pause','resume','next','close'} | volume_actions:
            return ToolResult(tool_name=self.tool_id,success=False,content='فرمان کنترل ویدیو معتبر نیست.')
        if (action=='set_volume' and (type(p.get('volume')) is not int or not 0<=p['volume']<=100)
                or action in {'volume_down','volume_up'} and
                (type(p.get('step',15)) is not int or not 1<=p.get('step',15)<=100)):
            return ToolResult(tool_name=self.tool_id,success=False,content='درصد صدا باید عدد صحیح بین صفر و صد باشد؛ گام تغییر بین ۱ و ۱۰۰.')
        page=_state.get('media_page')
        try:
            if (page is None or page.is_closed() or
                    urlsplit(page.url).hostname not in {'www.youtube.com','youtube.com'} or
                    urlsplit(page.url).path!='/watch'):
                return ToolResult(tool_name=self.tool_id,success=False,
                                  content='ویدیوی فعالی در مرورگر خورشید نیست.')
            if action=='close':
                page.close()
                if _state.get('page') is page:
                    _state['page']=None
                    _elements.clear()
                _state['media_page']=None
                return ToolResult(tool_name=self.tool_id,content='تب ویدیو بسته شد.')
            video=page.locator('video').first
            if action in volume_actions:
                changed=page.evaluate('''({action,volume,step})=>{
                    const v=document.querySelector('video'), p=document.querySelector('#movie_player');
                    if(!v) return false;
                    if(action==='mute'||action==='unmute') {
                        const muted=action==='mute';
                        if(p&&typeof p[muted?'mute':'unMute']==='function') p[muted?'mute':'unMute']();
                        v.muted=muted;
                    } else {
                        const current=p&&typeof p.getVolume==='function'?p.getVolume():v.volume*100;
                        const target=Math.max(0,Math.min(100,action==='set_volume'?volume:
                            current+(action==='volume_up'?step:-step)));
                        if(p&&typeof p.setVolume==='function') p.setVolume(target);
                        v.volume=target/100;
                        if(action!=='volume_down') {
                            if(p&&typeof p.unMute==='function') p.unMute();
                            v.muted=false;
                        }
                    }
                    return true;
                }''', {'action':action,'volume':p.get('volume'),'step':p.get('step',15)})
                if not changed:
                    return ToolResult(tool_name=self.tool_id,success=False,content='پخش‌کنندهٔ ویدیو پیدا نشد؛ صدا تغییر نکرد.')
            elif action=='pause':
                video.evaluate('(v)=>v.pause()')
                page.wait_for_function('()=>document.querySelector("video")?.paused===true',timeout=5000)
            elif action=='resume':
                video.evaluate('(v)=>Promise.race([v.play().then(()=>true).catch(()=>false),new Promise(r=>setTimeout(()=>r(false),3000))])')
                page.wait_for_function('()=>{const v=document.querySelector("video");return v&&!v.paused&&v.currentTime>0;}',timeout=7000)
            elif action=='next':
                old_url=page.url
                button=page.locator('.ytp-next-button').first
                if not button.count() or not button.is_visible():
                    return ToolResult(tool_name=self.tool_id,success=False,content='دکمهٔ ویدیوی بعدی در دسترس نیست.')
                button.click(timeout=5000)
                page.wait_for_function('(old)=>location.href!==old',arg=old_url,timeout=7000)
            state=_youtube_state(page)
            error=state.get('player_error') or state.get('media_error')
            playing=bool(state.get('playing')) and not state.get('advertisement') and not error
            state['playing']=bool(playing)
            note=('پخش مکث شد.' if action=='pause' else 'ویدیوی پیشنهادی بعدی باز شد.' if action=='next'
                  else 'ویدیو در حال پخش است.' if playing else 'ویدیو اکنون در حال پخش نیست.')
            if action in volume_actions:
                if state.get('volume') is None or state.get('muted') is None:
                    return ToolResult(tool_name=self.tool_id,success=False,content='وضعیت صدای ویدیو تأیید نشد.',metadata=state)
                note=('صدای ویدیو قطع است.' if state['muted'] else f"صدای ویدیو روی {state['volume']} درصد است.")
            if error:
                note+=' خطای پخش: '+str(error)
            return ToolResult(tool_name=self.tool_id,success=not bool(error),content=note,metadata=state)
        except Exception as exc:
            return ToolResult(tool_name=self.tool_id,success=False,
                              content='کنترل پخش انجام نشد: '+str(exc)[:350])
