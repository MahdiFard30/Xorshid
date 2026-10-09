"""OpenAI-compatible engine — با urllib خالص (بدون وابستگی) + استریم + structured.

کار می‌کند با: OpenAI، DeepSeek، OpenRouter، Together، vLLM، LM Studio،
Ollama (پورت /v1) و هر سرور OpenAI-compatible دیگر.
"""

from __future__ import annotations

import json
import os
import urllib.request
import urllib.error
from typing import Any, Dict

from ultimate_khorshid.core.registry import EngineRegistry
from ultimate_khorshid.engine.base import EngineConnectionError, InferenceEngine


@EngineRegistry.register("openai_compat")
@EngineRegistry.register("openai")
class OpenAICompatEngine(InferenceEngine):
    engine_id = "openai_compat"
    supports_streaming = True

    def __init__(self, api_key: str = "", base_url: str = "https://api.openai.com/v1",
                 timeout: float = 120.0) -> None:
        from ultimate_khorshid.core.vault import get_secret
        self.api_key = api_key or get_secret("OPENAI_API_KEY")
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1")).rstrip("/")
        self.timeout = timeout

    def _model_name(self, model: str) -> str:
        # "openai/gpt-4o-mini" -> "gpt-4o-mini"
        if "/" in model and not model.startswith("http"):
            return model.split("/", 1)[1]
        return model

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    def _payload(self, messages, model, *, tools=None, temperature=0.7,
                 max_tokens=1024, stream=False, **kw) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": kw.pop("real_model", None) or self._model_name(model),
            "messages": [_clean(m) for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": stream,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = kw.get("tool_choice", "auto")
        rf = kw.get("response_format")
        if isinstance(rf, dict) and rf.get("type"):
            payload["response_format"] = rf  # json_object / json_schema passthrough
        return payload

    def generate(self, messages, model, *, tools=None, temperature=0.7, max_tokens=1024, **kw):
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(messages, model, tools=tools, temperature=temperature,
                                max_tokens=max_tokens, stream=False, **kw)
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:800]
            raise EngineConnectionError(f"HTTP {e.code}: {body}")
        except Exception as e:
            raise EngineConnectionError(f"Connection failed: {e}")
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise EngineConnectionError(f"Bad response: {str(data)[:500]}")
        tool_calls = []
        for tc in choice.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            tool_calls.append({"name": fn.get("name", ""), "arguments": fn.get("arguments", "{}"), "id": tc.get("id", "")})
        res = {
            "content": choice.get("content") or "",
            "tool_calls": tool_calls,
            "finish_reason": data["choices"][0].get("finish_reason", "stop"),
            "usage": data.get("usage", {}),
        }
        return _apply_schema(res, kw)

    def generate_stream(self, messages, model, *, tools=None, temperature=0.7,
                        max_tokens=1024, **kw):
        from ultimate_khorshid.engine.streaming import (
            OAIToolAccumulator, oai_delta_text, oai_delta_tools, oai_finish, parse_sse_line)
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(messages, model, tools=tools, temperature=temperature,
                                max_tokens=max_tokens, stream=True, **kw)
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                     headers=self._headers(), method="POST")
        try:
            resp = urllib.request.urlopen(req, timeout=self.timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")[:800]
            raise EngineConnectionError(f"HTTP {e.code}: {body}")
        except Exception as e:
            raise EngineConnectionError(f"Connection failed: {e}")
        parts, acc, finish = [], OAIToolAccumulator(), "stop"
        try:
            for raw in resp:
                obj = parse_sse_line(raw.decode("utf-8", "replace"))
                if not obj or obj.get("__done__"):
                    continue
                d = oai_delta_text(obj)
                if d:
                    parts.append(d)
                    yield {"delta": d, "done": False}
                acc.add(oai_delta_tools(obj))
                f = oai_finish(obj)
                if f:
                    finish = f
        finally:
            try:
                resp.close()
            except Exception:
                pass
        res = {"content": "".join(parts), "tool_calls": acc.build(),
               "finish_reason": finish or "stop", "usage": {}}
        yield {"delta": "", "done": True, "result": _apply_schema(res, kw)}

    def health(self) -> Dict[str, Any]:
        try:
            req = urllib.request.Request(f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
            with urllib.request.urlopen(req, timeout=8) as resp:
                return {"engine": self.engine_id, "ok": resp.status == 200, "base_url": self.base_url}
        except Exception as e:
            return {"engine": self.engine_id, "ok": False, "error": str(e)[:200]}


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


def _clean(m: Dict[str, Any]) -> Dict[str, Any]:
    out = {"role": m.get("role"), "content": m.get("content", "")}
    for k in ("name", "tool_call_id", "tool_calls"):
        if m.get(k) is not None:
            out[k] = m[k]
    # tool_calls به فرمت OpenAI
    if isinstance(out.get("tool_calls"), list) and out["tool_calls"] and "function" not in out["tool_calls"][0]:
        out["tool_calls"] = [
            {"id": tc.get("id", ""), "type": "function",
             "function": {"name": tc.get("name"), "arguments": tc.get("arguments", "{}")}}
            for tc in out["tool_calls"]  # type: ignore
        ]
    return out
