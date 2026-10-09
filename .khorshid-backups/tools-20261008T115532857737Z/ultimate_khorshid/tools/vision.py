"""بینایی — فهمیدن محتوای عکس/اسکرین‌شات با Gemini (نیاز به GEMINI_API_KEY)."""

from __future__ import annotations

import base64
import json
import os
import urllib.request
import urllib.error
from typing import Any

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec


@ToolRegistry.register("vision_ask")
class VisionAskTool(BaseTool):
    tool_id = "vision_ask"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vision_ask",
            description="پرسیدن سؤال از روی یک عکس (پیش‌فرض: آخرین اسکرین‌شات؛ اگر نباشد خودش می‌گیرد).",
            parameters={"type": "object", "properties": {
                "question": {"type": "string"},
                "image_path": {"type": "string"}}, "required": ["question"]},
            category="vision", timeout_seconds=90.0)

    def execute(self, **p: Any) -> ToolResult:
        q = str(p.get("question", "")).strip()
        if not q:
            return ToolResult(tool_name="vision_ask", content="سؤالی نیست.", success=False)
        from ultimate_khorshid.core.vault import get_secret
        key = get_secret("GEMINI_API_KEY") or get_secret("GOOGLE_API_KEY")
        if not key:
            return ToolResult(tool_name="vision_ask",
                              content="بینایی به GEMINI_API_KEY نیاز دارد.", success=False)
        img = str(p.get("image_path", "") or "")
        if not img:
            try:
                from ultimate_khorshid.tools.desktop import last_screenshot, take_screenshot
                img = last_screenshot() or take_screenshot()
            except Exception as e:
                return ToolResult(tool_name="vision_ask", content=f"عکسی نیست: {e}", success=False)
        if not os.path.exists(img):
            return ToolResult(tool_name="vision_ask", content=f"فایل نیست: {img}", success=False)
        try:
            with open(img, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            mime = "image/png" if img.lower().endswith(".png") else "image/jpeg"
            payload = {"contents": [{"role": "user", "parts": [
                {"text": q[:2000]},
                {"inlineData": {"mimeType": mime, "data": b64}}]}]}
            req = urllib.request.Request(
                "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
                data=json.dumps(payload).encode(),
                headers={"Content-Type": "application/json", "x-goog-api-key": key})
            with urllib.request.urlopen(req, timeout=80) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            txt = data["candidates"][0]["content"]["parts"][0].get("text", "")
            return ToolResult(tool_name="vision_ask",
                              content=f"👁️ ({os.path.basename(img)}):\n{txt[:4000]}")
        except Exception as e:
            return ToolResult(tool_name="vision_ask", content=f"خطا: {e}", success=False)


# ------------------------------------------------- Grounding با شبکه (SoM) ---

GRID_COLS, GRID_ROWS = 8, 6  # A..H × 1..6


def grid_overlay(src: str, dst: str = "") -> tuple:
    """کشیدن شبکه شماره‌دار روی اسکرین‌شات. (مسیر خروجی، عرض، ارتفاع)."""
    from PIL import Image, ImageDraw
    img = Image.open(src).convert("RGB")
    w, h = img.size
    d = ImageDraw.Draw(img)
    cw, ch = w / GRID_COLS, h / GRID_ROWS
    for i in range(GRID_COLS + 1):
        d.line([(i * cw, 0), (i * cw, h)], fill=(255, 60, 60), width=2)
    for j in range(GRID_ROWS + 1):
        d.line([(0, j * ch), (w, j * ch)], fill=(255, 60, 60), width=2)
    for i in range(GRID_COLS):
        for j in range(GRID_ROWS):
            label = f"{chr(65 + i)}{j + 1}"
            x, y = i * cw + 6, j * ch + 4
            d.rectangle([x - 2, y - 2, x + 26, y + 16], fill=(255, 60, 60))
            d.text((x, y), label, fill=(255, 255, 255))
    out = dst or (src + ".grid.png")
    img.save(out)
    return out, w, h


def parse_cell(answer: str):
    """'C4' → (col, row) صفرمبنا. نامعتبر → None."""
    import re
    m = re.search(r"\b([A-H])\s*([1-6])\b", (answer or "").upper())
    if not m:
        return None
    return ord(m.group(1)) - 65, int(m.group(2)) - 1


def cell_center(col: int, row: int, w: int, h: int) -> tuple:
    return int((col + 0.5) * w / GRID_COLS), int((row + 0.5) * h / GRID_ROWS)


@ToolRegistry.register("vision_locate")
class VisionLocateTool(BaseTool):
    tool_id = "vision_locate"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vision_locate",
            description="پیدا کردن مختصات یک چیز روی صفحه (دکمه/آیکون/متن) با شبکه SoM. خروجی: x,y.",
            parameters={"type": "object", "properties": {
                "target": {"type": "string", "description": "توصیف هدف، مثل: دکمه آبی ورود"},
                "image_path": {"type": "string"}}, "required": ["target"]},
            category="vision", timeout_seconds=120.0)

    def execute(self, **p: Any) -> ToolResult:
        target = str(p.get("target", "")).strip()
        if not target:
            return ToolResult(tool_name="vision_locate", content="هدفی داده نشد.",
                              success=False)
        import importlib.util
        if importlib.util.find_spec("PIL") is None:
            return ToolResult(tool_name="vision_locate",
                              content='Pillow لازم است: pip install -e ".[desktop]"',
                              success=False)
        img = str(p.get("image_path", "") or "")
        if not img:
            try:
                from ultimate_khorshid.tools.desktop import last_screenshot, take_screenshot
                img = last_screenshot() or take_screenshot()
            except Exception as e:
                return ToolResult(tool_name="vision_locate",
                                  content=f"عکسی نیست: {e}", success=False)
        try:
            grid, w, h = grid_overlay(img)
        except Exception as e:
            return ToolResult(tool_name="vision_locate", content=f"خطای شبکه: {e}",
                              success=False)
        q = (f"روی این تصویر یک شبکه A1 تا H6 کشیده شده. «{target}» در کدام خانه است؟ "
             "فقط نام خانه را بگو (مثل C4). اگر نیست بگو NONE.")
        r = VisionAskTool().execute(question=q, image_path=grid)
        if not r.success:
            return ToolResult(tool_name="vision_locate", content=r.content, success=False)
        cell = parse_cell(r.content)
        if cell is None:
            return ToolResult(tool_name="vision_locate",
                              content=f"خانه‌ای پیدا نشد. جواب مدل: {r.content[:200]}",
                              success=False)
        x, y = cell_center(*cell, w, h)
        label = f"{chr(65 + cell[0])}{cell[1] + 1}"
        return ToolResult(tool_name="vision_locate",
                          content=f"📍 {target} → خانه {label} → x={x}, y={y} "
                                  f"(عکس شبکه: {grid})",
                          metadata={"x": x, "y": y, "cell": label, "grid": grid})


@ToolRegistry.register("vision_click")
class VisionClickTool(BaseTool):
    tool_id = "vision_click"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="vision_click",
            description="کلیک روی یک چیز روی صفحه با توصیفش (پیدا کن + کلیک کن).",
            parameters={"type": "object", "properties": {
                "target": {"type": "string"}}, "required": ["target"]},
            category="vision", timeout_seconds=120.0)

    def execute(self, **p: Any) -> ToolResult:
        loc = VisionLocateTool().execute(target=str(p.get("target", "")))
        if not loc.success:
            return ToolResult(tool_name="vision_click", content=loc.content, success=False)
        try:
            x, y = int(loc.metadata["x"]), int(loc.metadata["y"])
        except Exception:
            return ToolResult(tool_name="vision_click",
                              content="مختصات نامعتبر از locate.", success=False)
        try:
            from ultimate_khorshid.tools.desktop import MouseClickTool
            r = MouseClickTool().execute(x=x, y=y)
            ok = r.success
            detail = r.content[:200]
        except Exception as e:
            return ToolResult(tool_name="vision_click",
                              content=f"کلیک نشد (ابزار دسکتاپ؟): {e}", success=False)
        return ToolResult(tool_name="vision_click",
                          content=f"🖱️ کلیک شد: {p.get('target')} در x={x}, y={y} — {detail}",
                          success=ok)
