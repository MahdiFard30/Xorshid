"""هلپرهای استریم موتورها — پارس SSE/NDJSON (خالص، قابل تست آفلاین).

پروتکل‌ها:
- OpenAI-compat: خطوط `data: {...}` + پایان `data: [DONE]`
- Ollama: هر خط یک JSON کامل (`{"message": {...}, "done": bool}`)
- Gemini streamGenerateContent?alt=sse: خطوط `data: {...}`
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def parse_sse_line(line: str) -> Optional[Dict[str, Any]]:
    """یک خط استریم → آبجکت. پایان/خالی/ping → None."""
    t = (line or "").strip()
    if not t or t.startswith(":"):
        return None
    if t == "data: [DONE]" or t == "[DONE]":
        return {"__done__": True}
    if t.startswith("data:"):
        t = t[5:].strip()
    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def oai_delta_text(obj: Dict[str, Any]) -> str:
    try:
        return obj["choices"][0].get("delta", {}).get("content") or ""
    except Exception:
        return ""


def oai_delta_tools(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    try:
        return obj["choices"][0].get("delta", {}).get("tool_calls") or []
    except Exception:
        return []


def oai_finish(obj: Dict[str, Any]) -> str:
    try:
        return obj["choices"][0].get("finish_reason") or ""
    except Exception:
        return ""


class OAIToolAccumulator:
    """انباشت فرگمنت‌های tool_calls استریم OpenAI (بر اساس index)."""

    def __init__(self) -> None:
        self._by_idx: Dict[int, Dict[str, str]] = {}

    def add(self, frags: List[Dict[str, Any]]) -> None:
        for f in frags:
            i = int(f.get("index", 0))
            slot = self._by_idx.setdefault(i, {"id": "", "name": "", "args": ""})
            if f.get("id"):
                slot["id"] = str(f["id"])
            fn = f.get("function") or {}
            if fn.get("name"):
                slot["name"] = str(fn["name"])
            if fn.get("arguments"):
                slot["args"] += str(fn["arguments"])

    def build(self) -> List[Dict[str, Any]]:
        out = []
        for i in sorted(self._by_idx):
            s = self._by_idx[i]
            out.append({"name": s["name"], "arguments": s["args"] or "{}",
                        "id": s["id"] or f"stream_{i}"})
        return out


def ollama_delta_text(obj: Dict[str, Any]) -> str:
    try:
        return (obj.get("message") or {}).get("content") or ""
    except Exception:
        return ""


def ollama_done(obj: Dict[str, Any]) -> bool:
    return bool(obj.get("done"))


def gemini_delta_text(obj: Dict[str, Any]) -> str:
    try:
        parts = (obj["candidates"][0].get("content") or {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts if p.get("text"))
    except Exception:
        return ""


def gemini_delta_calls(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    try:
        parts = (obj["candidates"][0].get("content") or {}).get("parts") or []
        for p in parts:
            if "functionCall" in p:
                fc = p["functionCall"]
                out.append({"name": fc.get("name", ""),
                            "arguments": json.dumps(fc.get("args") or {},
                                                    ensure_ascii=False)})
    except Exception:
        pass
    return out
