"""ابزارهای ضروری: think / calculator / datetime / sysinfo."""

from __future__ import annotations

import ast
import datetime as _dt
import math
import operator
import os
import platform
import shutil
from typing import Any

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec


@ToolRegistry.register("think")
class ThinkTool(BaseTool):
    tool_id = "think"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="think",
            description="دفترچه تفکر مرحله‌به‌مرحله برای استدلال قبل از اقدام. همیشه قبل از کارهای چندمرحله‌ای از آن استفاده کن.",
            parameters={"type": "object", "properties": {
                "thought": {"type": "string", "description": "تفکر گام‌به‌گام"}}, "required": ["thought"]},
            category="reasoning")

    def execute(self, **p: Any) -> ToolResult:
        return ToolResult(tool_name="think", content=f"💭 ثبت شد: {p.get('thought','')[:1500]}", success=True)


_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
           ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_FUNCS = {"abs": abs, "round": round, "min": min, "max": max, "sqrt": math.sqrt,
          "log": math.log, "log10": math.log10, "sin": math.sin, "cos": math.cos,
          "tan": math.tan, "pi": math.pi, "e": math.e, "ceil": math.ceil,
          "floor": math.floor, "pow": pow, "sum": sum}


def _ev(node: ast.AST) -> Any:
    if isinstance(node, ast.Expression):
        return _ev(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_ev(node.left), _ev(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_ev(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _FUNCS:
        fn = _FUNCS[node.func.id]
        if not callable(fn):
            return fn
        return fn(*[_ev(a) for a in node.args])
    if isinstance(node, ast.Name) and node.id in _FUNCS and not callable(_FUNCS[node.id]):
        return _FUNCS[node.id]
    if isinstance(node, ast.List):
        return [_ev(e) for e in node.elts]
    raise ValueError(f"عبارت غیرمجاز: {type(node).__name__}")


@ToolRegistry.register("calculator")
class CalculatorTool(BaseTool):
    tool_id = "calculator"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="calculator",
            description="ماشین‌حساب امن (توابع ریاضی: sqrt/log/sin/cos/pi...). مثال: 2**10 + sqrt(16)",
            parameters={"type": "object", "properties": {
                "expression": {"type": "string"}}, "required": ["expression"]},
            category="reasoning")

    def execute(self, **p: Any) -> ToolResult:
        expr = str(p.get("expression", "")).strip().replace("×", "*").replace("÷", "/").replace("^", "**")
        try:
            val = _ev(ast.parse(expr, mode="eval"))
            return ToolResult(tool_name="calculator", content=f"{expr} = {val}", success=True,
                              metadata={"value": val})
        except Exception as e:
            return ToolResult(tool_name="calculator", content=f"خطای محاسبه: {e}", success=False)


@ToolRegistry.register("datetime_now")
class DatetimeTool(BaseTool):
    tool_id = "datetime_now"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="datetime_now",
            description="تاریخ و ساعت فعلی سیستم (میلادی + شمسی).",
            parameters={"type": "object", "properties": {
                "timezone": {"type": "string", "description": "نام تایم‌زون، مثل Asia/Tehran"}}},
            category="system")

    def execute(self, **p: Any) -> ToolResult:
        from zoneinfo import ZoneInfo
        from ultimate_khorshid.tools.jalali import gregorian_to_jalali
        zone = str(p.get("timezone", "") or "").strip()
        try:
            now = _dt.datetime.now(ZoneInfo(zone)) if zone else _dt.datetime.now().astimezone()
        except (KeyError, ValueError) as exc:
            return ToolResult(tool_name="datetime_now", content=f"تایم‌زون نامعتبر: {zone}: {exc}", success=False)
        jy, jm, jd = gregorian_to_jalali(now.year, now.month, now.day)
        jalali = f"\nشمسی: {jy:04d}/{jm:02d}/{jd:02d} {now.strftime('%H:%M')}"
        return ToolResult(tool_name="datetime_now",
                          content=f"میلادی: {now.strftime('%Y-%m-%d %H:%M:%S %Z')}{jalali}\nروز هفته: {now.strftime('%A')}")


@ToolRegistry.register("sysinfo")
class SysInfoTool(BaseTool):
    tool_id = "sysinfo"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="sysinfo", description="مشخصات سیستم: OS، CPU، رم، دیسک، پایتون.",
                        parameters={"type": "object", "properties": {}}, category="system")

    def execute(self, **p: Any) -> ToolResult:
        import sys
        disk = shutil.disk_usage(os.path.expanduser("~"))
        mem = ""
        try:
            if os.path.exists("/proc/meminfo"):
                txt = open("/proc/meminfo").read()
                total = [l for l in txt.splitlines() if l.startswith("MemTotal")][0].split()[1]
                avail = [l for l in txt.splitlines() if l.startswith("MemAvailable")][0].split()[1]
                mem = f"\nرم کل: {int(total)//1024}MB | آزاد: {int(avail)//1024}MB"
        except Exception:
            pass
        return ToolResult(tool_name="sysinfo", content=(
            f"سیستم‌عامل: {platform.system()} {platform.release()} ({platform.machine()})\n"
            f"پایتون: {sys.version.split()[0]}\n"
            f"CPU: {os.cpu_count()} هسته\n"
            f"دیسک home: آزاد {disk.free//2**30}GB از {disk.total//2**30}GB{mem}\n"
            f"کاربر: {os.environ.get('USER','?')} | مسیر: {os.getcwd()}"))
