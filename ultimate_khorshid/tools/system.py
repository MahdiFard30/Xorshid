"""ابزارهای سیستم — process / git / todo (لیست کارها)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, List

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec


@ToolRegistry.register("process_list")
class ProcessListTool(BaseTool):
    tool_id = "process_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="process_list",
            description="لیست پردازش‌های در حال اجرا (فیلتر اختیاری).",
            parameters={"type": "object", "properties": {
                "filter": {"type": "string"}, "limit": {"type": "integer"}}},
            category="system")

    def execute(self, **p: Any) -> ToolResult:
        try:
            if os.name == "nt":
                r = subprocess.run(["tasklist", "/FO", "CSV"], capture_output=True, text=True, timeout=10)
                lines = r.stdout.splitlines()
            else:
                r = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=10)
                lines = r.stdout.splitlines()
            flt = str(p.get("filter", "") or "").lower()
            if flt:
                lines = [l for l in lines if flt in l.lower()]
            lim = int(p.get("limit", 30) or 30)
            return ToolResult(tool_name="process_list",
                              content="🧩 پردازش‌ها:\n" + "\n".join(lines[:lim]))
        except Exception as e:
            return ToolResult(tool_name="process_list", content=f"خطا: {e}", success=False)


@ToolRegistry.register("git")
class GitTool(BaseTool):
    tool_id = "git"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="git",
            description="عملیات گیت: status/log/diff/commit/pull/push. commit نیاز به تأیید دارد.",
            parameters={"type": "object", "properties": {
                "action": {"type": "string", "description": "status|log|diff|add|commit|pull|push"},
                "message": {"type": "string"}, "path": {"type": "string"}},
                "required": ["action"]},
            category="dev", requires_confirmation=False)

    def execute(self, **p: Any) -> ToolResult:
        action = str(p.get("action", "status")).lower()
        cwd = os.path.expanduser(str(p.get("path", ".") or "."))
        cmds = {
            "status": ["git", "status", "-sb"],
            "log": ["git", "log", "--oneline", "-15"],
            "diff": ["git", "diff", "--stat"],
            "add": ["git", "add", "-A"],
            "pull": ["git", "pull", "--ff-only"],
            "push": ["git", "push"],
        }
        try:
            if action == "commit":
                msg = str(p.get("message", "") or "Update by Khorshid").strip()
                subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True, timeout=20)
                r = subprocess.run(["git", "commit", "-m", msg], cwd=cwd, capture_output=True, text=True, timeout=20)
            elif action in cmds:
                r = subprocess.run(cmds[action], cwd=cwd, capture_output=True, text=True, timeout=30)
            else:
                return ToolResult(tool_name="git", content=f"action نامعتبر: {action}", success=False)
            out = (r.stdout or "") + (r.stderr or "")
            return ToolResult(tool_name="git", content=f"git {action}:\n{out[:4000] or '(خالی)'}",
                              success=r.returncode == 0)
        except Exception as e:
            return ToolResult(tool_name="git", content=f"خطا: {e}", success=False)


def _todo_path() -> Path:
    fp = Path.home() / ".ultimate-jarvis" / "todos.json"
    fp.parent.mkdir(parents=True, exist_ok=True)
    return fp


def _load_todos() -> List[dict]:
    fp = _todo_path()
    if not fp.exists():
        return []
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_todos(items: List[dict]) -> None:
    _todo_path().write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")


@ToolRegistry.register("todo")
class TodoTool(BaseTool):
    tool_id = "todo"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="todo",
            description="لیست کارها: add/list/done/clear. برای پیگیری اهداف چندمرحله‌ای.",
            parameters={"type": "object", "properties": {
                "action": {"type": "string"}, "text": {"type": "string"},
                "id": {"type": "integer"}}, "required": ["action"]},
            category="productivity")

    def execute(self, **p: Any) -> ToolResult:
        action = str(p.get("action", "list")).lower()
        items = _load_todos()
        if action == "add":
            text = str(p.get("text", "")).strip()
            if not text:
                return ToolResult(tool_name="todo", content="متن کار خالی است.", success=False)
            nid = (max([i["id"] for i in items]) + 1) if items else 1
            items.append({"id": nid, "text": text, "done": False,
                          "created": datetime.now().isoformat(timespec="minutes")})
            _save_todos(items)
            return ToolResult(tool_name="todo", content=f"✅ اضافه شد (#{nid}): {text}")
        if action == "list":
            if not items:
                return ToolResult(tool_name="todo", content="📋 لیست خالی است.")
            lines = [f"{'✅' if i['done'] else '⬜'} #{i['id']}: {i['text']}" for i in items]
            return ToolResult(tool_name="todo", content="📋 کارها:\n" + "\n".join(lines))
        if action == "done":
            tid = int(p.get("id", 0) or 0)
            for i in items:
                if i["id"] == tid:
                    i["done"] = True
                    _save_todos(items)
                    return ToolResult(tool_name="todo", content=f"✅ انجام شد: #{tid}")
            return ToolResult(tool_name="todo", content="پیدا نشد.", success=False)
        if action == "clear":
            _save_todos([i for i in items if not i["done"]])
            return ToolResult(tool_name="todo", content="🧹 انجام‌شده‌ها پاک شدند.")
        return ToolResult(tool_name="todo", content=f"action نامعتبر: {action}", success=False)
