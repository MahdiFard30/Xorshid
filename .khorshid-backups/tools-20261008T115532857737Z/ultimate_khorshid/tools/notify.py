"""ابزار اعلان دسکتاپ — نمایش نوتیفیکیشن سیستمی (برای یادآورها و تسک‌ها).

لینوکس: notify-send | مک: osascript | ویندوز: msg | همیشه: چاپ در ترمینال.
بدون هیچ وابستگی خارجی؛ اگر هیچ بک‌اندی نبود، فقط چاپ می‌کند و موفق است.
"""

from __future__ import annotations

import platform
import shutil
import subprocess

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec


def send_notification(title: str, message: str, timeout: int = 10) -> str:
    """ارسال نوتیفیکیشن. نام روش استفاده‌شده را برمی‌گرداند."""
    title, message = title.strip() or "خورشید 🤖", message.strip()
    sys = platform.system()
    try:
        if sys == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", "-t", str(timeout * 1000),
                            title, message], timeout=10, check=False)
            return "notify-send"
        if sys == "Darwin":  # macOS
            script = f'display notification "{message}" with title "{title}"'
            subprocess.run(["osascript", "-e", script], timeout=10, check=False)
            return "osascript"
        if sys == "Windows":
            subprocess.run(["msg", "*", f"{title}: {message}"],
                           timeout=10, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "msg"
    except Exception:
        pass
    print(f"\n🔔 {title}: {message}\n")
    return "terminal"


@ToolRegistry.register("notify")
class NotifyTool(BaseTool):
    tool_id = "notify"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="notify",
            description="نمایش اعلان دسکتاپ به کاربر (یادآور، پایان تسک طولانی...).",
            parameters={"type": "object", "properties": {
                "message": {"type": "string", "description": "متن اعلان"},
                "title": {"type": "string", "description": "عنوان (اختیاری)"}},
                        "required": ["message"]},
            category="system")

    def execute(self, **p):
        msg = str(p.get("message", "") or "").strip()
        if not msg:
            return ToolResult(tool_name="notify", content="متن اعلان خالی است.",
                              success=False)
        method = send_notification(str(p.get("title", "") or ""), msg)
        return ToolResult(tool_name="notify",
                          content=f"🔔 اعلان نمایش داده شد (روش: {method}).")
