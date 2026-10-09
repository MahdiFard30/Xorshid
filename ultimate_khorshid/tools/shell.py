"""ابزارهای اجرا — shell_exec و python_exec با سندباکس (docker/firejail/restricted).

امنیت لایه‌ای: بلاک‌لیست دستورات مرگبار + سندباکس قابل انتخاب + تایم‌اوت.
پارامتر sandbox: auto (پیش‌فرض، امن‌ترین موجود) | docker | firejail | off
"""

from __future__ import annotations

import os
import time
from typing import Any

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

MAX_OUT = 12_000

# دستورات فوق‌خطرناک — همیشه مسدود (حتی قبل از سندباکس)
BLOCKED = (
    "rm -rf /", "rm -rf /*", "mkfs", ":(){:|:&};:", "dd if=", "> /dev/sda",
    "shutdown -h now", "reboot -f", "chmod -R 777 /",
)


def _blocked(cmd: str) -> str:
    for b in BLOCKED:
        if b in cmd:
            return b
    return ""


def _clip(out: str) -> str:
    if len(out) > MAX_OUT:
        return out[:MAX_OUT] + f"\n… (کوتاه شد؛ {len(out)} کاراکتر)"
    return out


@ToolRegistry.register("shell_exec")
class ShellExecTool(BaseTool):
    tool_id = "shell_exec"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="shell_exec",
            description="اجرای دستور شل و برگرداندن stdout/stderr. sandbox: auto/docker/firejail/off.",
            parameters={"type": "object", "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "description": "ثانیه (پیش‌فرض ۳۰، حداکثر ۳۰۰)"},
                "working_dir": {"type": "string"},
                "sandbox": {"type": "string", "description": "auto/docker/firejail/off (پیش‌فرض auto)"}},
                "required": ["command"]},
            category="exec", requires_confirmation=True,
            timeout_seconds=90.0, required_capabilities=["code:execute"])

    def execute(self, **p: Any) -> ToolResult:
        from ultimate_khorshid.core.sandbox import run_shell
        cmd = str(p.get("command", "")).strip()
        if not cmd:
            return ToolResult(tool_name="shell_exec", content="دستوری داده نشد.", success=False)
        if (b := _blocked(cmd)):
            return ToolResult(tool_name="shell_exec", content=f"⛔ دستور مسدود: {b}", success=False)
        timeout = min(max(int(p.get("timeout", 30) or 30), 1), 300)
        cwd = os.path.expanduser(str(p.get("working_dir", "") or os.getcwd()))
        sandbox = str(p.get("sandbox", "auto") or "auto")
        t0 = time.time()
        rc, out, err, used = run_shell(cmd, backend=sandbox, workdir=cwd, timeout=timeout)
        body = out + (f"\n[stderr]\n{err}" if err else "")
        ms = (time.time() - t0) * 1000
        tag = {"docker": "🐳", "firejail": "🔥"}.get(used, "⚠️")
        note = "" if used != "restricted" else " (سندباکس واقعی در دسترس نبود؛ برای ایزوله کامل Docker نصب کن)"
        return ToolResult(
            tool_name="shell_exec",
            content=f"$ {cmd}\nexit={rc} | {tag} backend={used} {ms:.0f}ms{note}\n{_clip(body) or '(خروجی خالی)'}",
            success=rc == 0,
            metadata={"exit_code": rc, "sandbox": used})


@ToolRegistry.register("python_exec")
class PythonExecTool(BaseTool):
    tool_id = "python_exec"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="python_exec",
            description="اجرای کد پایتون در ساب‌پروسس ایزوله (stdout/stderr برمی‌گردد). sandbox: auto/docker/firejail/off.",
            parameters={"type": "object", "properties": {
                "code": {"type": "string"},
                "timeout": {"type": "integer", "description": "ثانیه (پیش‌فرض ۳۰)"},
                "sandbox": {"type": "string", "description": "auto/docker/firejail/off (پیش‌فرض auto)"}},
                "required": ["code"]},
            category="exec", requires_confirmation=True,
            timeout_seconds=90.0, required_capabilities=["code:execute"])

    def execute(self, **p: Any) -> ToolResult:
        from ultimate_khorshid.core.sandbox import run_python
        code = str(p.get("code", ""))
        if not code.strip():
            return ToolResult(tool_name="python_exec", content="کدی داده نشد.", success=False)
        if (b := _blocked(code)):
            return ToolResult(tool_name="python_exec", content=f"⛔ الگوی مسدود: {b}", success=False)
        timeout = min(max(int(p.get("timeout", 30) or 30), 1), 300)
        sandbox = str(p.get("sandbox", "auto") or "auto")
        t0 = time.time()
        rc, out, err, used = run_python(code, backend=sandbox, timeout=timeout)
        body = out + (f"\n[stderr]\n{err}" if err else "")
        ms = (time.time() - t0) * 1000
        tag = {"docker": "🐳", "firejail": "🔥"}.get(used, "⚠️")
        if rc == 0:
            return ToolResult(tool_name="python_exec",
                              content=f"✅ اجرا شد ({ms:.0f}ms) {tag} backend={used}:\n{_clip(body) or '(خروجی خالی)'}",
                              metadata={"sandbox": used})
        return ToolResult(tool_name="python_exec",
                          content=f"❌ خطای پایتون (exit={rc}) {tag} backend={used}:\n{_clip(body) or '(بدون خروجی)'}",
                          success=False, metadata={"sandbox": used, "exit_code": rc})
