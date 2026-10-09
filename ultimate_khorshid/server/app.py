"""Server — داشبورد فارسی + API کامل (روی stdlib http.server).

  GET  /                    داشبورد وب 🤖
  GET  /health  /v1/models  POST /v1/chat/completions  POST /ask
  Chat:     POST /api/chat  GET /api/history  POST /api/history/clear
  Settings: GET /api/settings  POST /api/settings
  Browser:  POST /api/browser {op,...}
  Quiz:     POST /api/quiz {url?, max?}
  Misc: /api/status /api/agents /api/tools /api/sysinfo /api/screenshot
        POST /api/speak  /api/todos  /api/memory
"""

from __future__ import annotations

import base64
import json
import sqlite3
import time
import urllib.parse
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from ultimate_khorshid.core.config import load_config

DASHBOARD = Path(__file__).parent / "dashboard.html"
HISTORY_DB = Path.home() / ".ultimate-jarvis" / "history.db"


def _run_query(query: str, agent: str, model: str = "") -> dict:
    from ultimate_khorshid.runtime import KhorshidRuntime
    cfg = load_config()
    if model:
        cfg.intelligence.default_model = model
    rt = KhorshidRuntime(cfg)
    r = rt.ask(query, agent=agent or cfg.agent.default_agent)
    return {"content": r.content, "turns": r.turns,
            "tools_used": [t.tool_name for t in r.tool_results],
            "tools": [{"name": t.tool_name, "success": t.success,
                       "content": t.content[:800]} for t in r.tool_results]}


def _hist_init() -> None:
    HISTORY_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(HISTORY_DB))
    c.execute("""CREATE TABLE IF NOT EXISTS chats(
        id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, agent TEXT,
        query TEXT, reply TEXT)""")
    c.commit()
    c.close()


def hist_add(agent: str, query: str, reply: str) -> None:
    try:
        _hist_init()
        c = sqlite3.connect(str(HISTORY_DB))
        c.execute("INSERT INTO chats(ts,agent,query,reply) VALUES(?,?,?,?)",
                  (datetime.now().isoformat(timespec="minutes"), agent,
                   query[:500], reply[:1500]))
        c.execute("DELETE FROM chats WHERE id NOT IN (SELECT id FROM chats ORDER BY id DESC LIMIT 100)")
        c.commit()
        c.close()
    except Exception:
        pass


def hist_list(limit: int = 15) -> list:
    try:
        _hist_init()
        c = sqlite3.connect(str(HISTORY_DB))
        rows = c.execute("SELECT id,ts,agent,query FROM chats ORDER BY id DESC LIMIT ?",
                         (limit,)).fetchall()
        c.close()
        return [{"id": r[0], "ts": r[1], "agent": r[2], "query": r[3]} for r in rows]
    except Exception:
        return []


def hist_clear() -> None:
    try:
        _hist_init()
        c = sqlite3.connect(str(HISTORY_DB))
        c.execute("DELETE FROM chats")
        c.commit()
        c.close()
    except Exception:
        pass


def _browser_op(data: dict) -> dict:
    """اجرای مستقیم ابزار مرورگر برای داشبورد."""
    from ultimate_khorshid.runtime import _ensure_imports
    from ultimate_khorshid.tools.base import ToolExecutor
    from ultimate_khorshid.core.registry import ToolRegistry
    from ultimate_khorshid.core.types import ToolCall
    _ensure_imports()
    op = str(data.get("op", "snapshot"))
    mapping = {
        "open": ("browser_open", {"url": str(data.get("url", ""))}),
        "snapshot": ("browser_snapshot", {}),
        "forms": ("browser_forms", {}),
        "click": ("browser_click", {"ref": str(data.get("ref", ""))}),
        "type": ("browser_type", {"ref": str(data.get("ref", "")),
                                  "text": str(data.get("text", "")),
                                  "submit": bool(data.get("submit", False))}),
        "check": ("browser_check", {"ref": str(data.get("ref", ""))}),
        "press": ("browser_press", {"key": str(data.get("key", "Enter"))}),
        "text": ("browser_text", {"max_chars": 4000}),
        "google": ("browser_google_search", {"query": str(data.get("query", ""))}),
        "close": ("browser_close", {}),
    }
    if op == "shot":
        ex = ToolExecutor([ToolRegistry.create("browser_screenshot")])
        r = ex.execute(ToolCall(name="browser_screenshot", arguments="{}"))
        if not r.success:
            return {"ok": False, "error": r.content[:300]}
        import re
        m = re.search(r"(/[\w\-./]+\.png)", r.content)
        if m and Path(m.group(1)).exists():
            b64 = base64.b64encode(Path(m.group(1)).read_bytes()).decode()
            return {"ok": True, "image": "data:image/png;base64," + b64}
        return {"ok": False, "error": "فایل عکس پیدا نشد"}
    if op not in mapping:
        return {"ok": False, "error": f"op نامعتبر: {op}"}
    name, params = mapping[op]
    try:
        ex = ToolExecutor([ToolRegistry.create(name)])
    except KeyError:
        return {"ok": False, "error": f"ابزار {name} ثبت نشده"}
    r = ex.execute(ToolCall(name=name, arguments=json.dumps(params, ensure_ascii=False)))
    return {"ok": r.success, "result": r.content[:6000]}


def _run_quiz(data: dict) -> dict:
    from ultimate_khorshid.runtime import KhorshidRuntime
    from ultimate_khorshid.agents.base import AgentContext
    from ultimate_khorshid.core.types import Conversation
    rt = KhorshidRuntime()
    conv = Conversation()
    url = str(data.get("url", "") or "")
    q = str(data.get("query", "") or "") or f"سوال‌های این صفحه را جواب بده: {url}"
    conv.add("user", q)
    ctx = AgentContext(conversation=conv, tools=rt.tool_names,
                       metadata={"url": url,
                                 "max_questions": int(data.get("max", 30) or 30),
                                 "submit": bool(data.get("submit", False))})
    r = rt.build_agent("quiz").run(ctx)
    return {"ok": True, "report": r.content,
            "answered": r.metadata.get("answered", 0)}


class Handler(BaseHTTPRequestHandler):
    server_version = "UltimateKhorshid/1.0"

    def _send(self, obj: Any, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, data: bytes, mime: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", 0))
            return json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        except Exception:
            return {}

    # -- GET --
    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path, qs = parsed.path, urllib.parse.parse_qs(parsed.query)
        try:
            if path == "/":
                return self._send_bytes(DASHBOARD.read_bytes(), "text/html; charset=utf-8")
            if path == "/health":
                return self._send({"status": "ok", "service": "ultimate-khorshid"})
            if path == "/v1/models":
                from ultimate_khorshid.intelligence.catalog import BUILTIN_MODELS
                return self._send({"object": "list", "data": [
                    {"id": m.id, "object": "model"} for m in BUILTIN_MODELS]})
            if path == "/api/status":
                from ultimate_khorshid.runtime import list_agents, list_tools
                cfg = load_config()
                return self._send({"engine": cfg.engine.default,
                                   "model": cfg.intelligence.default_model,
                                   "agent": cfg.agent.default_agent,
                                   "agents": len(list_agents()), "tools": len(list_tools())})
            if path == "/api/agents":
                from ultimate_khorshid.runtime import list_agents
                return self._send({"agents": list_agents()})
            if path == "/api/tools":
                from ultimate_khorshid.runtime import _ensure_imports
                from ultimate_khorshid.core.registry import ToolRegistry
                _ensure_imports()
                out = []
                for n, cls in sorted(ToolRegistry.items()):
                    try:
                        s = cls().spec
                        out.append({"name": n, "desc": s.description[:80], "category": s.category})
                    except Exception:
                        pass
                return self._send({"tools": out})
            if path == "/api/sysinfo":
                from ultimate_khorshid.tools.essentials import SysInfoTool
                return self._send({"text": SysInfoTool().execute().content})
            if path == "/api/screenshot":
                from ultimate_khorshid.tools.desktop import get_screenshot_bytes
                data, mime = get_screenshot_bytes()
                return self._send_bytes(data, mime)
            if path == "/api/todos":
                from ultimate_khorshid.tools.system import _load_todos
                return self._send({"items": _load_todos()})
            if path == "/api/memory":
                from ultimate_khorshid.memory.store import get_memory
                mem = get_memory()
                q = qs.get("q", [""])[0]
                hits = mem.list_recent(8) if (q in ("", "&recent=1")) else mem.search(q, 8)
                return self._send({"items": [{"id": h.id, "text": h.text,
                                              "created": h.created} for h in hits]})
            if path == "/api/settings":
                from ultimate_khorshid.core.settings import get_settings
                from ultimate_khorshid.hotkey.manager import describe
                s = get_settings()
                s["hotkey_describe"] = describe(s["hotkey"])
                return self._send({"ok": True, "settings": s})
            if path == "/api/history":
                return self._send({"items": hist_list(int(qs.get("limit", ["15"])[0] or 15))})
        except Exception as e:
            return self._send({"error": str(e)[:500]}, 500)
        return self._send({"error": "not found"}, 404)

    # -- POST --
    def do_POST(self) -> None:  # noqa: N802
        data = self._body()
        try:
            if self.path == "/ask":
                out = _run_query(str(data.get("query", "")), str(data.get("agent", "computer")),
                                 str(data.get("model", "")))
                return self._send({"ok": True, **out})
            if self.path == "/v1/chat/completions":
                user_q = ""
                for m in reversed(data.get("messages", [])):
                    if m.get("role") == "user":
                        user_q = str(m.get("content", ""))
                        break
                out = _run_query(user_q, "computer", str(data.get("model", "")))
                return self._send({
                    "id": f"chatcmpl-{int(time.time())}", "object": "chat.completion",
                    "created": int(time.time()), "model": data.get("model", "ultimate-khorshid"),
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": out["content"]},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}})
            if self.path == "/api/chat":
                agent = str(data.get("agent", "") or "computer")
                msg = str(data.get("message", ""))
                out = _run_query(msg, agent)
                hist_add(agent, msg, out["content"])
                return self._send({"ok": True, "reply": out["content"],
                                   "tools": out["tools"], "turns": out["turns"]})
            if self.path == "/api/speak":
                from ultimate_khorshid.voice.engines import api_key, GeminiTTS
                if not api_key():
                    return self._send({"error": "no gemini key — browser TTS fallback"}, 503)
                from ultimate_khorshid.voice import audio as A
                wav = GeminiTTS().synthesize(str(data.get("text", ""))[:1200], A.tmp_wav("ui_speak"))
                return self._send_bytes(Path(wav).read_bytes(), "audio/wav")
            if self.path == "/api/todos":
                from ultimate_khorshid.tools.system import TodoTool
                r = TodoTool().execute(action=str(data.get("action", "list")),
                                       text=str(data.get("text", "")),
                                       id=int(data.get("id", 0) or 0))
                return self._send({"ok": r.success, "result": r.content})
            if self.path == "/api/memory":
                from ultimate_khorshid.memory.store import get_memory
                mid = get_memory().add(str(data.get("text", ""))[:2000], "dashboard")
                return self._send({"ok": True, "id": mid})
            if self.path == "/api/settings":
                from ultimate_khorshid.core.settings import set_settings
                from ultimate_khorshid.hotkey.manager import describe
                allowed = {k: v for k, v in data.items()
                           if k in ("hotkey", "hotkey_action", "engine", "model", "voice") and v}
                s = set_settings(**allowed)
                s["hotkey_describe"] = describe(s["hotkey"])
                return self._send({"ok": True, "settings": s})
            if self.path == "/api/browser":
                return self._send(_browser_op(data))
            if self.path == "/api/quiz":
                return self._send(_run_quiz(data))
            if self.path == "/api/history/clear":
                hist_clear()
                return self._send({"ok": True})
            if self.path == "/api/vision":
                from ultimate_khorshid.tools.vision import VisionAskTool
                q = str(data.get("question", "") or "این صفحه را دقیق توصیف کن.")
                r = VisionAskTool().execute(question=q[:500])
                return self._send({"ok": r.success, "result": r.content})
        except Exception as e:
            return self._send({"error": str(e)[:500]}, 500)
        return self._send({"error": "not found"}, 404)

    def log_message(self, *a: Any) -> None:
        pass


def serve(host: str = "127.0.0.1", port: int = 8899, open_browser: bool = False) -> None:
    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    srv = ThreadingHTTPServer((host, port), Handler)
    print(f"🤖 داشبورد خورشید: http://{host}:{port}  (Ctrl+C برای توقف)")
    print("   API: /api/chat /api/quiz /api/browser /api/settings /api/speak | سازگار با OpenAI: /v1/chat/completions")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nخاموش شد.")


def create_fastapi_app():  # pragma: no cover
    from fastapi import FastAPI  # type: ignore
    app = FastAPI(title="Ultimate Khorshid")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/ask")
    def ask_ep(body: dict):
        return {"ok": True, **_run_query(str(body.get("query", "")), str(body.get("agent", "computer")))}

    return app
