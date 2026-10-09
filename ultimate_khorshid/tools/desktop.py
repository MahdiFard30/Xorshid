"""ابزارهای دسکتاپ — اسکرین‌شات، موس، کیبورد، باز کردن برنامه/لینک، کلیپ‌بورد.

نیاز: pip install -e ".[desktop]"  (pyautogui, mss, pillow, pyperclip)
بدون آن‌ها هم ایجنت کار می‌کند؛ فقط این ابزارها راهنمای نصب می‌دهند.
"""

from __future__ import annotations

import os
import shutil
import shlex
import platform
import subprocess
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Tuple

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

DESKTOP_PIP = 'pip install -e ".[desktop]"  # یا: pip install pyautogui mss pillow pyperclip'


def shots_dir() -> Path:
    d = Path.home() / ".ultimate-jarvis" / "shots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def last_screenshot() -> str:
    shots = sorted(shots_dir().glob("shot_*.png"), key=lambda p: p.stat().st_mtime)
    return str(shots[-1]) if shots else ""


def take_screenshot(path: str = "") -> str:
    """گرفتن اسکرین‌شات. مسیر فایل را برمی‌گرداند یا خطا می‌دهد."""
    path = path or str(shots_dir() / f"shot_{datetime.now():%Y%m%d_%H%M%S}.png")
    # ۱) mss (سریع، بدون نیاز به X اضافه در بیشتر موارد)
    try:
        import mss  # type: ignore
        import mss.tools  # type: ignore
        with mss.mss() as sct:
            img = sct.grab(sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0])
            mss.tools.to_png(img.rgb, img.size, output=path)
        return path
    except Exception as e1:
        # ۲) PIL
        try:
            from PIL import ImageGrab  # type: ignore
            ImageGrab.grab().save(path)
            return path
        except Exception as e2:
            # ۳) ابزار سیستم (لینوکس)
            for cmd in (["gnome-screenshot", "-f", path], ["scrot", path],
                        ["import", "-window", "root", path]):
                try:
                    subprocess.run(cmd, check=True, capture_output=True, timeout=15)
                    if os.path.exists(path):
                        return path
                except Exception:
                    continue
            raise RuntimeError(
                f"اسکرین‌شات ممکن نشد (نمایشگر/کتابخانه نیست): {e1} / {e2}\n"
                f"راه‌حل: {DESKTOP_PIP} و اجرای روی سیستم با دسکتاپ.")


def get_screenshot_bytes() -> Tuple[bytes, str]:
    """برای داشبورد: بایت PNG یا SVG جایگزین + mime."""
    try:
        p = take_screenshot()
        return Path(p).read_bytes(), "image/png"
    except Exception as e:
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450">
<rect width="800" height="450" rx="16" fill="#0b1220"/>
<text x="400" y="200" font-size="28" fill="#7dd3fc" text-anchor="middle">📸 اسکرین‌شات در دسترس نیست</text>
<text x="400" y="245" font-size="16" fill="#94a3b8" text-anchor="middle">{str(e)[:90]}</text>
<text x="400" y="280" font-size="15" fill="#64748b" text-anchor="middle">روی سیستم خودت (با دسکتاپ) اجرا کن + pip install -e ".[desktop]"</text>
</svg>"""
        return svg.encode("utf-8"), "image/svg+xml"


def _pagui():
    try:
        import pyautogui  # type: ignore
        pyautogui.FAILSAFE = True
        return pyautogui
    except ImportError:
        raise RuntimeError(f"pyautogui نصب نیست. نصب: {DESKTOP_PIP}")


# ------------------------------------------------------------- ابزارها ---

@ToolRegistry.register("screenshot")
class ScreenshotTool(BaseTool):
    tool_id = "screenshot"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="screenshot", description="گرفتن عکس از صفحه نمایش (مسیر فایل PNG برمی‌گردد).",
            parameters={"type": "object", "properties": {
                "save_to": {"type": "string"}}}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        try:
            fp = take_screenshot(str(p.get("save_to", "") or ""))
            size = os.path.getsize(fp)
            return ToolResult(tool_name="screenshot",
                              content=f"📸 ذخیره شد: {fp} ({size//1024}KB)\n"
                                      f"برای فهمیدن محتوایش از vision_ask استفاده کن.")
        except Exception as e:
            return ToolResult(tool_name="screenshot", content=str(e), success=False)


@ToolRegistry.register("mouse_move")
class MouseMoveTool(BaseTool):
    tool_id = "mouse_move"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="mouse_move", description="حرکت موس به مختصات x,y.",
            parameters={"type": "object", "properties": {
                "x": {"type": "integer"}, "y": {"type": "integer"}},
                "required": ["x", "y"]}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        try:
            g = _pagui()
            g.moveTo(int(p.get("x", 0)), int(p.get("y", 0)), duration=0.3)
            return ToolResult(tool_name="mouse_move",
                              content=f"🖱️ موس رفت به ({p.get('x')},{p.get('y')})")
        except Exception as e:
            return ToolResult(tool_name="mouse_move", content=str(e), success=False)


@ToolRegistry.register("mouse_click")
class MouseClickTool(BaseTool):
    tool_id = "mouse_click"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="mouse_click", description="کلیک موس (چپ/راست/دوبار).",
            parameters={"type": "object", "properties": {
                "x": {"type": "integer"}, "y": {"type": "integer"},
                "button": {"type": "string", "description": "left|right|middle"},
                "clicks": {"type": "integer"}}, "required": []},
            category="desktop", requires_confirmation=False)

    def execute(self, **p: Any) -> ToolResult:
        try:
            g = _pagui()
            kw: dict = {}
            if p.get("x") is not None and p.get("y") is not None:
                kw["x"], kw["y"] = int(p["x"]), int(p["y"])
            g.click(button=str(p.get("button", "left") or "left"),
                    clicks=int(p.get("clicks", 1) or 1), **kw)
            at = f" در ({kw.get('x')},{kw.get('y')})" if kw else " در موقعیت فعلی"
            return ToolResult(tool_name="mouse_click", content=f"🖱️ کلیک شد{at}")
        except Exception as e:
            return ToolResult(tool_name="mouse_click", content=str(e), success=False)


@ToolRegistry.register("mouse_scroll")
class MouseScrollTool(BaseTool):
    tool_id = "mouse_scroll"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="mouse_scroll", description="اسکرول (مثبت=بالا، منفی=پایین).",
            parameters={"type": "object", "properties": {"amount": {"type": "integer"}}},
            category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        try:
            _pagui().scroll(int(p.get("amount", -500) or -500))
            return ToolResult(tool_name="mouse_scroll", content="🖱️ اسکرول شد.")
        except Exception as e:
            return ToolResult(tool_name="mouse_scroll", content=str(e), success=False)


@ToolRegistry.register("key_press")
class KeyPressTool(BaseTool):
    tool_id = "key_press"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="key_press", description="فشردن کلید (enter, esc, tab, f5, ...).",
            parameters={"type": "object", "properties": {"key": {"type": "string"}},
                        "required": ["key"]}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        try:
            _pagui().press(str(p.get("key", "enter")))
            return ToolResult(tool_name="key_press", content=f"⌨️ کلید {p.get('key')} زده شد.")
        except Exception as e:
            return ToolResult(tool_name="key_press", content=str(e), success=False)


@ToolRegistry.register("key_hotkey")
class KeyHotkeyTool(BaseTool):
    tool_id = "key_hotkey"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="key_hotkey", description="کلید ترکیبی؛ مثل ctrl+t یا alt+tab (با + یا , جدا کن).",
            parameters={"type": "object", "properties": {"keys": {"type": "string"}},
                        "required": ["key"] if False else ["keys"]}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        try:
            import re
            keys = [k.strip() for k in re.split(r"[+,]", str(p.get("keys", ""))) if k.strip()]
            if not keys:
                return ToolResult(tool_name="key_hotkey", content="کلیدی داده نشد.", success=False)
            _pagui().hotkey(*keys)
            return ToolResult(tool_name="key_hotkey", content=f"⌨️ {'+'.join(keys)} زده شد.")
        except Exception as e:
            return ToolResult(tool_name="key_hotkey", content=str(e), success=False)


@ToolRegistry.register("type_text")
class TypeTextTool(BaseTool):
    tool_id = "type_text"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="type_text", description="تایپ متن با کیبورد در برنامه فعال (برای فارسی از clipboard_type استفاده کن).",
            parameters={"type": "object", "properties": {
                "text": {"type": "string"},
                "clipboard_type": {"type": "boolean", "description": "تایپ via کلیپ‌بورد (بهتر برای فارسی)"}},
                "required": ["text"]}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        text = str(p.get("text", ""))
        try:
            g = _pagui()
            if p.get("clipboard_type"):
                import pyperclip  # type: ignore
                pyperclip.copy(text)
                time.sleep(0.2)
                g.hotkey("ctrl", "v")
            else:
                g.write(text, interval=0.02)
            return ToolResult(tool_name="type_text", content=f"⌨️ تایپ شد ({len(text)} حرف).")
        except Exception as e:
            return ToolResult(tool_name="type_text", content=str(e), success=False)


@ToolRegistry.register("open_url")
class OpenUrlTool(BaseTool):
    tool_id = "open_url"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="open_url", description="باز کردن لینک در مرورگر پیش‌فرض سیستم.",
            parameters={"type": "object", "properties": {"url": {"type": "string"}},
                        "required": ["url"]}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        url = str(p.get("url", "")).strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            opened = webbrowser.open(url, new=2)
            if not opened:
                return ToolResult(tool_name="open_url", content="مرورگر پیش‌فرض سیستم باز نشد؛ تنظیم مرورگر پیش‌فرض را بررسی کنید.", success=False)
            return ToolResult(tool_name="open_url", content=f"درخواست بازکردن {url} به مرورگر سیستم ارسال شد.")
        except Exception as e:
            return ToolResult(tool_name="open_url", content=str(e), success=False)


@ToolRegistry.register("open_app")
class OpenAppTool(BaseTool):
    tool_id = "open_app"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="open_app", description="اجرای/باز کردن یک برنامه یا فایل با برنامه پیش‌فرض.",
            parameters={"type": "object", "properties": {"target": {"type": "string"}},
                        "required": ["target"]}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        t = str(p.get("target", "")).strip()
        sys = platform.system()
        try:
            if sys == "Darwin":
                subprocess.Popen(["open", t])
            elif sys == "Windows":
                os.startfile(t)  # type: ignore[attr-defined]
            else:
                if not t:
                    raise ValueError("نام برنامه یا مسیر خالی است.")
                args = shlex.split(t)
                executable = shutil.which(args[0]) if args else None
                command = [executable, *args[1:]] if executable and not os.path.isfile(os.path.expanduser(t)) else ["xdg-open", os.path.expanduser(t)]
                process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    rc = process.wait(timeout=0.4)
                    if rc != 0:
                        raise RuntimeError(f"برنامه با کد {rc} خارج شد")
                except subprocess.TimeoutExpired:
                    pass
            return ToolResult(tool_name="open_app", content=f"🚀 درخواست اجرا ارسال شد: {t}")
        except Exception as e:
            return ToolResult(tool_name="open_app", content=f"خطا: {e}", success=False)


@ToolRegistry.register("clipboard")
class ClipboardTool(BaseTool):
    tool_id = "clipboard"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="clipboard", description="خواندن/نوشتن کلیپ‌بورد.",
            parameters={"type": "object", "properties": {
                "action": {"type": "string", "description": "get|set"},
                "text": {"type": "string"}}}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        try:
            import pyperclip  # type: ignore
            if str(p.get("action", "get")).lower() == "set":
                pyperclip.copy(str(p.get("text", "")))
                return ToolResult(tool_name="clipboard", content="📋 در کلیپ‌بورد ذخیره شد.")
            return ToolResult(tool_name="clipboard",
                              content=f"📋:\n{pyperclip.paste()[:2000]}")
        except ImportError:
            return ToolResult(tool_name="clipboard",
                              content=f"pyperclip نصب نیست: {DESKTOP_PIP}", success=False)
        except Exception as e:
            return ToolResult(tool_name="clipboard", content=str(e), success=False)


@ToolRegistry.register("display_info")
class DisplayInfoTool(BaseTool):
    tool_id = "display_info"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="display_info", description="ابعاد صفحه و موقعیت موس.",
            parameters={"type": "object", "properties": {}}, category="desktop")

    def execute(self, **p: Any) -> ToolResult:
        try:
            g = _pagui()
            w, h = g.size()
            x, y = g.position()
            return ToolResult(tool_name="display_info",
                              content=f"🖥️ صفحه: {w}×{h} | موس: ({x},{y})")
        except Exception as e:
            return ToolResult(tool_name="display_info", content=str(e), success=False)
