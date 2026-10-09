"""Ollama native engine — /api/chat با urllib خالص (+ استریم + خروجی ساخت‌یافته)."""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict

from ultimate_khorshid.core.registry import EngineRegistry
from ultimate_khorshid.engine.base import EngineConnectionError, InferenceEngine


@EngineRegistry.register("ollama")
class OllamaEngine(InferenceEngine):
    engine_id = "ollama"
    supports_streaming = True

    def __init__(self, host: str = "", timeout: float = 180.0) -> None:
        self.host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")
        self.timeout = timeout

    def _model(self, model: str) -> str:
        return model.split("/", 1)[1] if model.startswith("ollama/") else model

    def _payload(self, messages, model, *, tools=None, temperature=0.7,
                 max_tokens=1024, stream=False, **kw) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": self._model(model),
            "messages": [{"role": m.get("role"), "content": str(m.get("content", ""))} for m in messages],
            "stream": stream,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = tools
        rf = kw.get("response_format") or {}
        if isinstance(rf, dict) and rf.get("type") == "json_object":
            payload["format"] = "json"
        return payload

    def generate(self, messages, model, *, tools=None, temperature=0.7, max_tokens=1024, **kw):
        url = f"{self.host}/api/chat"
        payload = self._payload(messages, model, tools=tools, temperature=temperature,
                                max_tokens=max_tokens, stream=False, **kw)
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise EngineConnectionError(f"Ollama failed ({self.host}): {e}")
        msg = data.get("message", {})
        tool_calls = []
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            args = fn.get("arguments", {})
            tool_calls.append({"name": fn.get("name", ""),
                               "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
                               "id": f"ollama_{len(tool_calls)}"})
        res = {"content": msg.get("content", "") or "", "tool_calls": tool_calls,
               "finish_reason": "tool_calls" if tool_calls else "stop",
               "usage": {"prompt_tokens": data.get("prompt_eval_count", 0),
                         "completion_tokens": data.get("eval_count", 0)}}
        return _apply_schema(res, kw)

    def generate_stream(self, messages, model, *, tools=None, temperature=0.7,
                        max_tokens=1024, **kw):
        from ultimate_khorshid.engine.streaming import ollama_delta_text, ollama_done
        url = f"{self.host}/api/chat"
        payload = self._payload(messages, model, tools=tools, temperature=temperature,
                                max_tokens=max_tokens, stream=True, **kw)
        req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except Exception as e:
            raise EngineConnectionError(f"Ollama failed ({self.host}): {e}")
        parts, tool_calls = [], []
        tin = tout = 0
        try:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                d = ollama_delta_text(obj)
                if d:
                    parts.append(d)
                    yield {"delta": d, "done": False}
                tcs = (obj.get("message") or {}).get("tool_calls") or []
                if tcs:
                    tool_calls = [{"name": (t.get("function") or {}).get("name", ""),
                                   "arguments": json.dumps((t.get("function") or {}).get("arguments", {}),
                                                            ensure_ascii=False),
                                   "id": f"ollama_{i}"} for i, t in enumerate(tcs)]
                if ollama_done(obj):
                    tin, tout = obj.get("prompt_eval_count", 0), obj.get("eval_count", 0)
        finally:
            try:
                resp.close()
            except Exception:
                pass
        res = {"content": "".join(parts), "tool_calls": tool_calls,
               "finish_reason": "tool_calls" if tool_calls else "stop",
               "usage": {"prompt_tokens": tin, "completion_tokens": tout}}
        yield {"delta": "", "done": True, "result": _apply_schema(res, kw)}

    def health(self) -> Dict[str, Any]:
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=6) as resp:
                data = json.loads(resp.read().decode())
                models = [m.get("name") for m in data.get("models", [])]
                return {"engine": "ollama", "ok": True, "models": models}
        except Exception as e:
            return {"engine": "ollama", "ok": False, "error": str(e)[:200]}


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
