"""Gemini native engine — REST :generateContent با function calling (فقط urllib، بدون وابستگی).

کلید رایگان: https://aistudio.google.com
  export GEMINI_API_KEY="..."
  export KHORSHID_ENGINE=gemini KHORSHID_MODEL=gemini/gemini-2.0-flash
"""

from __future__ import annotations

import json
import urllib.request
import urllib.error
from typing import Any, Dict, List, Tuple

from ultimate_khorshid.core.registry import EngineRegistry
from ultimate_khorshid.engine.base import EngineConnectionError, InferenceEngine


@EngineRegistry.register("gemini")
class GeminiEngine(InferenceEngine):
    engine_id = "gemini"
    supports_streaming = True
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str = "", timeout: float = 120.0) -> None:
        from ultimate_khorshid.core.vault import get_secret
        self.api_key = (api_key or get_secret("GEMINI_API_KEY")
                        or get_secret("GOOGLE_API_KEY"))
        self.timeout = timeout

    def _model(self, model: str) -> str:
        if "/" in model:
            return model.split("/", 1)[1]
        return model or "gemini-2.0-flash"

    def _payload(self, messages, temperature=0.7, max_tokens=1024,
                 tools=None, **kw) -> Dict[str, Any]:
        system_txt, contents = convert_messages(messages)
        payload: Dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                "temperature": max(0.0, min(2.0, temperature)),
                "maxOutputTokens": max(1, min(8192, max_tokens)),
            },
        }
        rf = kw.get("response_format") or {}
        schema = kw.get("json_schema")
        if (isinstance(rf, dict) and rf.get("type") == "json_object") or schema:
            payload["generationConfig"]["responseMimeType"] = "application/json"
            if isinstance(schema, dict):
                payload["generationConfig"]["responseSchema"] = _sanitize_schema(schema)
        if system_txt.strip():
            payload["systemInstruction"] = {"parts": [{"text": system_txt[:20000]}]}
        if tools:
            payload["tools"] = [{"functionDeclarations": [convert_tool(t) for t in tools]}]
        return payload

    def _headers(self) -> Dict[str, str]:
        return {"Content-Type": "application/json", "x-goog-api-key": self.api_key}

    def generate(self, messages, model, *, tools=None, temperature=0.7, max_tokens=1024, **kw):
        if not self.api_key:
            raise EngineConnectionError(
                "کلید Gemini تنظیم نشده! از https://aistudio.google.com بگیرید و:\n"
                "  export GEMINI_API_KEY='...'")
        name = kw.get("real_model") or self._model(model)
        payload = self._payload(messages, temperature, max_tokens, tools, **kw)
        req = urllib.request.Request(
            f"{self.BASE}/{name}:generateContent",
            data=json.dumps(payload).encode("utf-8"), headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:600]
            raise EngineConnectionError(f"Gemini HTTP {e.code}: {body}")
        except Exception as e:
            raise EngineConnectionError(f"Gemini connection failed: {e}")
        return _apply_schema(parse_response(data), kw)

    def generate_stream(self, messages, model, *, tools=None, temperature=0.7,
                        max_tokens=1024, **kw):
        from ultimate_khorshid.engine.streaming import (
            gemini_delta_calls, gemini_delta_text, parse_sse_line)
        if not self.api_key:
            raise EngineConnectionError("کلید Gemini تنظیم نشده (GEMINI_API_KEY).")
        name = kw.get("real_model") or self._model(model)
        payload = self._payload(messages, temperature, max_tokens, tools, **kw)
        req = urllib.request.Request(
            f"{self.BASE}/{name}:streamGenerateContent?alt=sse",
            data=json.dumps(payload).encode("utf-8"), headers=self._headers())
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:600]
            raise EngineConnectionError(f"Gemini HTTP {e.code}: {body}")
        except Exception as e:
            raise EngineConnectionError(f"Gemini connection failed: {e}")
        parts, calls = [], []
        try:
            for raw in resp:
                obj = parse_sse_line(raw.decode("utf-8", "replace"))
                if not obj or obj.get("__done__"):
                    continue
                d = gemini_delta_text(obj)
                if d:
                    parts.append(d)
                    yield {"delta": d, "done": False}
                for c in gemini_delta_calls(obj):
                    calls.append({**c, "id": f"gem_{len(calls)}"})
        finally:
            try:
                resp.close()
            except Exception:
                pass
        res = {"content": "".join(parts), "tool_calls": calls,
               "finish_reason": "tool_calls" if calls else "stop", "usage": {}}
        yield {"delta": "", "done": True, "result": _apply_schema(res, kw)}

    def health(self) -> Dict[str, Any]:
        if not self.api_key:
            return {"engine": "gemini", "ok": False, "error": "no api key (GEMINI_API_KEY)"}
        try:
            req = urllib.request.Request(
                f"{self.BASE}/gemini-2.0-flash",
                headers={"x-goog-api-key": self.api_key})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return {"engine": "gemini", "ok": True, "model": data.get("name", "")}
        except Exception as e:
            return {"engine": "gemini", "ok": False, "error": str(e)[:200]}


def _apply_schema(res: Dict[str, Any], kw: Dict[str, Any]) -> Dict[str, Any]:
    schema = kw.get("json_schema")
    if not schema:
        return res
    from ultimate_khorshid.core.jsonx import parse_strict
    try:
        obj, errs = parse_strict(str(res.get("content", "")), schema)
        res["parsed"], res["schema_errors"] = obj, errs
    except Exception as e:
        res["parsed"], res["schema_errors"] = None, [f"parse: {e}"]
    return res


# ---------------------------------------------------------------------------
# تبدیل فرمت‌ها (قابل تست بدون اینترنت)
# ---------------------------------------------------------------------------

def _append(contents: List[Dict[str, Any]], role: str, *parts: Dict[str, Any]) -> None:
    # جمینای نقش‌های پشت‌سرهم یکسان را قبول نمی‌کند → ادغام
    if contents and contents[-1]["role"] == role:
        contents[-1]["parts"].extend(parts)
    else:
        contents.append({"role": role, "parts": list(parts)})


def convert_messages(messages: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
    """OpenAI-style → (system_text, gemini contents)."""
    system_parts: List[str] = []
    contents: List[Dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        content = m.get("content", "") or ""
        if role == "system":
            if content.strip():
                system_parts.append(content)
            continue
        if role == "tool":
            _append(contents, "user", {"functionResponse": {
                "name": m.get("name") or "tool",
                "response": {"output": content[:8000] or "(empty)"}}})
            continue
        if role == "assistant":
            parts: List[Dict[str, Any]] = []
            if content.strip():
                parts.append({"text": content[:20000]})
            for tc in m.get("tool_calls") or []:
                if "function" in tc:  # شکل OpenAI
                    fn = tc["function"]
                    nm, ag = fn.get("name", ""), fn.get("arguments", "{}")
                else:  # شکل داخلی ما
                    nm, ag = tc.get("name", ""), tc.get("arguments", "{}")
                try:
                    args = json.loads(ag) if isinstance(ag, str) else (ag or {})
                except Exception:
                    args = {}
                if nm:
                    part = {"functionCall": {"name": nm, "args": args}}
                    sig = tc.get("thought_signature") or tc.get("thoughtSignature")
                    if sig:
                        part["thoughtSignature"] = sig
                    parts.append(part)
            _append(contents, "model", *(parts or [{"text": " "}]))
            continue
        # user
        _append(contents, "user", {"text": content if content.strip() else " "})
    if not contents:
        contents = [{"role": "user", "parts": [{"text": " "}]}]
    if contents[0]["role"] != "user":  # جمینای: پیام اول باید user باشد
        contents.insert(0, {"role": "user", "parts": [{"text": "شروع"}]})
    return "\n\n".join(system_parts), contents


_TYPE_MAP = {"int": "integer", "bool": "boolean", "dict": "object",
             "list": "array", "str": "string", "float": "number"}


def _sanitize_schema(s: Any) -> Dict[str, Any]:
    """فقط زیرمجموعه اسکیمای مورد قبول جمینای."""
    if not isinstance(s, dict):
        return {"type": "object"}
    out: Dict[str, Any] = {}
    for k in ("type", "description", "enum", "items", "required", "properties", "format"):
        if k in s:
            out[k] = s[k]
    if isinstance(out.get("properties"), dict):
        out["properties"] = {kk: _sanitize_schema(vv) for kk, vv in out["properties"].items()}
    if isinstance(out.get("items"), dict):
        out["items"] = _sanitize_schema(out["items"])
    t = str(out.get("type", "object")).lower()
    out["type"] = _TYPE_MAP.get(t, t if t in ("string", "number", "integer", "boolean", "array", "object") else "string")
    return out


def convert_tool(openai_tool: Dict[str, Any]) -> Dict[str, Any]:
    fn = openai_tool.get("function", openai_tool)
    params = fn.get("parameters") or {"type": "object", "properties": {}}
    return {"name": fn.get("name"), "description": (fn.get("description") or "")[:1500],
            "parameters": _sanitize_schema(params)}


def parse_response(data: Dict[str, Any]) -> Dict[str, Any]:
    cands = data.get("candidates") or []
    if not cands:
        fb = json.dumps(data.get("promptFeedback", {}), ensure_ascii=False)[:300]
        raise EngineConnectionError(f"Gemini پاسخی نداد (بلاک شد؟): {fb}")
    parts = (cands[0].get("content") or {}).get("parts") or []
    texts: List[str] = []
    calls: List[Dict[str, Any]] = []
    for p in parts:
        if p.get("text"):
            texts.append(p["text"])
        if "functionCall" in p:
            fc = p["functionCall"]
            call = {"name": fc.get("name", ""),
                    "arguments": json.dumps(fc.get("args") or {}, ensure_ascii=False),
                    "id": f"gem_{len(calls)}"}
            sig = p.get("thoughtSignature") or p.get("thought_signature")
            if sig:
                call["thought_signature"] = sig
            calls.append(call)
    usage = data.get("usageMetadata", {})
    return {"content": "".join(texts), "tool_calls": calls,
            "finish_reason": "tool_calls" if calls else "stop",
            "usage": {"prompt_tokens": usage.get("promptTokenCount", 0),
                      "completion_tokens": usage.get("candidatesTokenCount", 0)}}
