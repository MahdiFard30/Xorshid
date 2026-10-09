"""ابزارهای صوتی به‌صورت Tool — speak / listen (قابل استفاده توسط ایجنت)."""

from __future__ import annotations

from typing import Any
from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec


@ToolRegistry.register("speak")
class SpeakTool(BaseTool):
    tool_id = "speak"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="speak",
            description="خواندن متن با صدای بلند (TTS فارسی).",
            parameters={"type": "object", "properties": {
                "text": {"type": "string"},
                "save_to": {"type": "string", "description": "مسیر ذخیره WAV (اختیاری)"}},
                "required": ["text"]},
            category="voice", timeout_seconds=120.0)

    def execute(self, **p: Any) -> ToolResult:
        text = str(p.get("text", "")).strip()
        if not text:
            return ToolResult(tool_name="speak", content="متنی نیست.", success=False)
        try:
            from ultimate_khorshid.voice.engines import speak_text
            wav = speak_text(text[:1500], out=str(p.get("save_to", "") or ""))
            return ToolResult(tool_name="speak",
                              content=f"🔊 خوانده شد.{f' فایل: {wav}' if wav else ''}")
        except Exception as e:
            return ToolResult(tool_name="speak", content=f"خطای TTS: {e}", success=False)


@ToolRegistry.register("listen")
class ListenTool(BaseTool):
    tool_id = "listen"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="listen",
            description="گوش دادن به میکروفون و رونویسی حرف کاربر.",
            parameters={"type": "object", "properties": {
                "seconds": {"type": "integer", "description": "طول ضبط (پیش‌فرض ۵)"}},
                "required": []},
            category="voice", timeout_seconds=90.0)

    def execute(self, **p: Any) -> ToolResult:
        secs = min(max(int(p.get("seconds", 5) or 5), 1), 60)
        try:
            from ultimate_khorshid.voice import audio as A
            from ultimate_khorshid.voice.engines import transcribe_file
            wav = A.tmp_wav("khorshid_tool_listen")
            A.record_fixed(wav, seconds=secs)
            return ToolResult(tool_name="listen",
                              content=f"👂 شنیدم: {transcribe_file(wav)}")
        except Exception as e:
            return ToolResult(tool_name="listen", content=f"خطا: {e}", success=False)
