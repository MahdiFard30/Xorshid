"""ابزارهای فایل — خواندن/نوشتن/ویرایش/لیست/جست‌وجو/کپی/انتقال/حذف امن."""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Any, List

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

MAX_READ = 60_000
SENSITIVE = (".env", "id_rsa", "id_ed25519", ".pem", "credentials.json", ".git-credentials")


def _resolve(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p))).resolve()


def _guard(p: Path) -> str | None:
    name = p.name.lower()
    if any(s in name for s in SENSITIVE):
        return f"⛔ فایل حساس ({p.name}) — دسترسی مسدود."
    return None


@ToolRegistry.register("file_read")
class FileReadTool(BaseTool):
    tool_id = "file_read"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="file_read", description="خواندن فایل متنی (با شماره خط و صفحه‌بندی).",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "خط شروع (از ۱)"},
                "limit": {"type": "integer", "description": "تعداد خط"}},
                "required": ["path"]}, category="files")

    def execute(self, **p: Any) -> ToolResult:
        try:
            fp = _resolve(str(p.get("path", "")))
            if (g := _guard(fp)):
                return ToolResult(tool_name="file_read", content=g, success=False)
            if not fp.exists():
                return ToolResult(tool_name="file_read", content=f"فایل نیست: {fp}", success=False)
            if fp.is_dir():
                return ToolResult(tool_name="file_read", content=f"این دایرکتوری است، از file_list استفاده کن: {fp}", success=False)
            if fp.stat().st_size > 2_000_000:
                return ToolResult(tool_name="file_read", content="فایل بیش از ۲MB است.", success=False)
            lines = fp.read_text(encoding="utf-8", errors="replace").splitlines()
            off = max(int(p.get("offset", 1) or 1), 1) - 1
            lim = int(p.get("limit", 200) or 200)
            sel = lines[off:off + lim]
            body = "\n".join(f"{i+off+1:4d}│ {l}" for i, l in enumerate(sel))
            more = f"\n… ({len(lines)-off-len(sel)} خط دیگر)" if off + len(sel) < len(lines) else ""
            return ToolResult(tool_name="file_read", content=f"📄 {fp} ({len(lines)} خط):\n{body}{more}")
        except Exception as e:
            return ToolResult(tool_name="file_read", content=f"خطا: {e}", success=False)


@ToolRegistry.register("file_write")
class FileWriteTool(BaseTool):
    tool_id = "file_write"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="file_write", description="نوشتن/بازنویسی کامل فایل (پوشه والد ساخته می‌شود).",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}, "content": {"type": "string"},
                "append": {"type": "boolean"}}, "required": ["path", "content"]},
            category="files", requires_confirmation=False)

    def execute(self, **p: Any) -> ToolResult:
        try:
            fp = _resolve(str(p.get("path", "")))
            if (g := _guard(fp)):
                return ToolResult(tool_name="file_write", content=g, success=False)
            fp.parent.mkdir(parents=True, exist_ok=True)
            mode = "a" if p.get("append") else "w"
            fp.write_text(str(p.get("content", "")) if mode == "w" else fp.read_text(encoding="utf-8", errors="replace") + str(p.get("content", "")) if fp.exists() else str(p.get("content", "")), encoding="utf-8")
            return ToolResult(tool_name="file_write",
                              content=f"✅ نوشته شد: {fp} ({fp.stat().st_size} بایت)")
        except Exception as e:
            return ToolResult(tool_name="file_write", content=f"خطا: {e}", success=False)


@ToolRegistry.register("file_edit")
class FileEditTool(BaseTool):
    tool_id = "file_edit"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="file_edit", description="ویرایش دقیق: جایگزینی old_text با new_text (اولین تطابق).",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}, "old_text": {"type": "string"},
                "new_text": {"type": "string"}}, "required": ["path", "old_text", "new_text"]},
            category="files")

    def execute(self, **p: Any) -> ToolResult:
        try:
            fp = _resolve(str(p.get("path", "")))
            if (g := _guard(fp)):
                return ToolResult(tool_name="file_edit", content=g, success=False)
            text = fp.read_text(encoding="utf-8", errors="replace")
            old, new = str(p.get("old_text", "")), str(p.get("new_text", ""))
            if not old or old not in text:
                return ToolResult(tool_name="file_edit", content="old_text باید غیرخالی و دقیقاً مطابق متن فایل باشد؛ فایلی تغییر نکرد.", success=False)
            fp.write_text(text.replace(old, new, 1), encoding="utf-8")
            return ToolResult(tool_name="file_edit", content=f"✅ ویرایش شد: {fp}")
        except Exception as e:
            return ToolResult(tool_name="file_edit", content=f"خطا: {e}", success=False)


@ToolRegistry.register("file_list")
class FileListTool(BaseTool):
    tool_id = "file_list"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="file_list", description="لیست فایل‌ها و پوشه‌های یک مسیر (با الگوی glob).",
            parameters={"type": "object", "properties": {
                "path": {"type": "string"}, "pattern": {"type": "string"},
                "recursive": {"type": "boolean"}, "limit": {"type": "integer"}},
                "required": []}, category="files")

    def execute(self, **p: Any) -> ToolResult:
        try:
            base = _resolve(str(p.get("path", ".")))
            if not base.exists():
                return ToolResult(tool_name="file_list", content=f"مسیر نیست: {base}", success=False)
            pat = str(p.get("pattern", "*") or "*")
            rec = bool(p.get("recursive", False))
            lim = int(p.get("limit", 100) or 100)
            out: List[str] = []
            if base.is_file():
                return ToolResult(tool_name="file_list", content=f"📄 {base}")
            it = base.rglob(pat) if rec else base.glob(pat)
            for i, fp in enumerate(sorted(it)):
                if i >= lim:
                    out.append("… (محدود شد)")
                    break
                rel = fp.relative_to(base)
                if fp.is_dir():
                    out.append(f"📁 {rel}/")
                else:
                    out.append(f"📄 {rel} ({fp.stat().st_size}B)")
            return ToolResult(tool_name="file_list",
                              content=f"📂 {base}:\n" + ("\n".join(out) if out else "(خالی)"))
        except Exception as e:
            return ToolResult(tool_name="file_list", content=f"خطا: {e}", success=False)


@ToolRegistry.register("file_search")
class FileSearchTool(BaseTool):
    tool_id = "file_search"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="file_search", description="جست‌وجوی متنی (grep) در فایل‌ها با regex.",
            parameters={"type": "object", "properties": {
                "pattern": {"type": "string"}, "path": {"type": "string"},
                "glob": {"type": "string"}, "limit": {"type": "integer"}},
                "required": ["pattern"]}, category="files")

    def execute(self, **p: Any) -> ToolResult:
        try:
            rx = re.compile(str(p.get("pattern", "")), re.M)
            base = _resolve(str(p.get("path", ".") or "."))
            glob = str(p.get("glob", "*") or "*")
            lim = int(p.get("limit", 50) or 50)
            hits: List[str] = []
            files = [base] if base.is_file() else [f for f in base.rglob(glob) if f.is_file() and f.stat().st_size < 1_000_000][:500]
            for fp in files:
                if _guard(fp.resolve()):
                    continue
                try:
                    text = fp.read_text(encoding="utf-8", errors="ignore")
                except Exception:
                    continue
                for i, line in enumerate(text.splitlines(), 1):
                    if rx.search(line):
                        hits.append(f"{fp}:{i}: {line.strip()[:160]}")
                        if len(hits) >= lim:
                            break
                if len(hits) >= lim:
                    break
            if not hits:
                return ToolResult(tool_name="file_search", content="چیزی پیدا نشد.")
            return ToolResult(tool_name="file_search", content=f"🔍 {len(hits)} نتیجه:\n" + "\n".join(hits))
        except Exception as e:
            return ToolResult(tool_name="file_search", content=f"خطا: {e}", success=False)


@ToolRegistry.register("file_delete")
class FileDeleteTool(BaseTool):
    tool_id = "file_delete"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="file_delete", description="حذف فایل یا پوشه. ⚠️ خطرناک — نیاز به تأیید.",
            parameters={"type": "object", "properties": {"path": {"type": "string"}},
                        "required": ["path"]}, category="files",
            requires_confirmation=True, required_capabilities=["fs:delete"])

    def execute(self, **p: Any) -> ToolResult:
        try:
            raw = str(p.get("path", "")).strip()
            if not raw:
                return ToolResult(tool_name="file_delete", content="مسیر حذف خالی است.", success=False)
            fp = _resolve(raw)
            home = Path.home().resolve()
            # محافظت از مسیرهای حساس
            if fp == home or fp == Path("/") or str(fp) in ("/", str(home)):
                return ToolResult(tool_name="file_delete", content="⛔ حذف این مسیر ممنوع!", success=False)
            if not fp.exists():
                return ToolResult(tool_name="file_delete", content="مسیر وجود ندارد.", success=False)
            if fp.is_dir():
                shutil.rmtree(fp)
            else:
                fp.unlink()
            return ToolResult(tool_name="file_delete", content=f"🗑 حذف شد: {fp}")
        except Exception as e:
            return ToolResult(tool_name="file_delete", content=f"خطا: {e}", success=False)


@ToolRegistry.register("file_copy")
class FileCopyTool(BaseTool):
    tool_id = "file_copy"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="file_copy", description="کپی فایل/پوشه.",
            parameters={"type": "object", "properties": {
                "src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]},
            category="files")

    def execute(self, **p: Any) -> ToolResult:
        try:
            src, dst = _resolve(str(p.get("src"))), _resolve(str(p.get("dst")))
            if src.is_dir():
                shutil.copytree(src, dst, dirs_exist_ok=True)
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            return ToolResult(tool_name="file_copy", content=f"✅ کپی شد: {src} → {dst}")
        except Exception as e:
            return ToolResult(tool_name="file_copy", content=f"خطا: {e}", success=False)


@ToolRegistry.register("file_move")
class FileMoveTool(BaseTool):
    tool_id = "file_move"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="file_move", description="انتقال/تغییرنام فایل/پوشه.",
            parameters={"type": "object", "properties": {
                "src": {"type": "string"}, "dst": {"type": "string"}}, "required": ["src", "dst"]},
            category="files")

    def execute(self, **p: Any) -> ToolResult:
        try:
            src, dst = _resolve(str(p.get("src"))), _resolve(str(p.get("dst")))
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            return ToolResult(tool_name="file_move", content=f"✅ منتقل شد: {src} → {dst}")
        except Exception as e:
            return ToolResult(tool_name="file_move", content=f"خطا: {e}", success=False)
