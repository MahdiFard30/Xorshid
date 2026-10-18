"""Runtime — کارخانه ساخت ایجنت آماده‌به‌کار از روی کانفیگ (مثل manager در OpenJarvis).

یک خط برای اجرای کامل:
    from ultimate_khorshid.runtime import ask
    print(ask("ساعت چند است؟"))
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ultimate_khorshid.core.config import KhorshidConfig, load_config
from ultimate_khorshid.core.events import EventBus
from ultimate_khorshid.core.registry import AgentRegistry, ToolRegistry
from ultimate_khorshid.core.types import Conversation


TOOL_MODULES = ("mt5_demo", 'mt5_bridge', 'mt5_strategies', "essentials", "files", "shell", "web", "system", "memory_tools",
                "crypto", "desktop", "browser", "vision", "voice_tools",
                "weather", "notify")
AGENT_MODULES = ("simple", "react", "orchestrator", "codeact", "planner",
                 "computer", "researcher", "autonomous", "quiz", "supervisor")


def _ensure_imports() -> None:
    # رجیستر شدن همه ابزارها/ایجنت‌ها با ایمپورت
    import importlib
    for mod in TOOL_MODULES:
        importlib.import_module(f"ultimate_khorshid.tools.{mod}")
    for mod in AGENT_MODULES:
        importlib.import_module(f"ultimate_khorshid.agents.{mod}")


_ensure_imports()

PERSONA_KHORSHID = """تو خورشید نهایی هستی — دستیار کامپیوتری شخصی، وفادار، دقیق و کمی بذله‌گو.
فارسی روان حرف بزن. تاریخ امروز را از ابزار datetime_now بگیر، حدس نزن."""


def load_persona(name: str = "khorshid") -> str:
    if name == "jarvis":  # Existing user config: keep loading the renamed persona.
        name = "khorshid"
    fp = Path(__file__).parent / "prompts" / f"{name}.md"
    if fp.exists():
        try:
            return fp.read_text(encoding="utf-8")
        except Exception:
            pass
    return PERSONA_KHORSHID


class KhorshidRuntime:
    """ران‌تایم کامل: engine + tools + agent + memory + skills."""

    def __init__(self, cfg: Optional[KhorshidConfig] = None,
                 confirm_callback: Optional[Callable[[str], bool]] = None,
                 interactive: bool = False, allow_unconfirmed: bool = False) -> None:
        from ultimate_khorshid.engine.discovery import engine_for_model
        from ultimate_khorshid.tools.base import ToolExecutor
        from ultimate_khorshid.skills.manager import SkillManager

        _ensure_imports()
        self.cfg = cfg or load_config()
        self.bus = EventBus()
        self.model = self.cfg.intelligence.default_model
        self.engine = engine_for_model(self.model, self.cfg)
        if self.engine.engine_id == "gemini":
            from ultimate_khorshid.engine.response_failover import ResponseFailover
            self.engine = ResponseFailover(self.engine, self.cfg)

        # ابزارها
        wanted = self.cfg.agent.tools.strip()
        tools = []
        for name, cls in ToolRegistry.items():
            if wanted not in ("*", "all") and name not in [w.strip() for w in wanted.split(",")]:
                continue
            try:
                tools.append(cls())
            except Exception as exc:
                raise RuntimeError(f"Tool initialization failed: {name}: {exc}") from exc
        if wanted not in ("*", "all"):
            unknown = set(w.strip() for w in wanted.split(",") if w.strip()) - {t.spec.name for t in tools}
            if unknown:
                raise ValueError("Unknown configured tools: " + ", ".join(sorted(unknown)))
        self.executor = ToolExecutor(tools, bus=self.bus, interactive=interactive,
                                     confirm_callback=confirm_callback,
                                     allow_unconfirmed=allow_unconfirmed)
        self.tool_names = [t.spec.name for t in tools]
        self.skills = SkillManager([str(Path.home() / ".ultimate-jarvis" / "skills")])
        self.persona = load_persona(self.cfg.agent.persona)

    def build_agent(self, name: Optional[str] = None):
        name = name or self.cfg.agent.default_agent
        if not AgentRegistry.contains(name):
            name = "computer"
        cls = AgentRegistry.get(name)
        skill_txt = ""
        try:
            skill_txt = self.skills.inject(["persian-assistant"])
        except Exception:
            pass
        sys_prompt = self.persona + (f"\n\n{skill_txt}" if skill_txt else "")
        kwargs = dict(bus=self.bus, temperature=self.cfg.intelligence.temperature,
                      max_tokens=self.cfg.intelligence.max_tokens,
                      system_prompt=sys_prompt, max_turns=self.cfg.agent.max_turns)
        if getattr(cls, "accepts_tools", False):
            kwargs["executor"] = self.executor
        return cls(self.engine, self.model, **kwargs)

    def ask(self, query: str, agent: Optional[str] = None,
            memory: bool | None = None, stream: bool = False,
            on_token: Any = None, trace_name: str = "ask",
            extra_meta: Optional[Dict[str, str]] = None,
            session_id: str = "local", memory_scope: str = "local") -> Any:
        from ultimate_khorshid.memory.automatic import scoped_path, session_lock
        path = scoped_path(self.cfg.storage.db_path, memory_scope)
        with session_lock(path, session_id):
            return self._ask_remember(query, agent, memory, stream, on_token,
                                      trace_name, extra_meta, session_id, memory_scope)

    def _ask_remember(self, query: str, agent: Optional[str] = None,
            memory: bool | None = None, stream: bool = False,
            on_token: Any = None, trace_name: str = "ask",
            extra_meta: Optional[Dict[str, str]] = None,
            session_id: str = "local", memory_scope: str = "local") -> Any:
        """Remember turns and outcomes across runtime instances/restarts.

        memory=False disables reads, automatic writes and memory tools for this turn.
        Non-local callers must supply a trusted scope (e.g. Telegram chat/user ID).
        """
        import json
        import warnings
        from ultimate_khorshid.memory.automatic import AutomaticMemory, memory_context, scoped_path
        enabled = self.cfg.agent.context_from_memory if memory is None else memory
        path = scoped_path(self.cfg.storage.db_path, memory_scope)
        history, background, saved = [], "", None
        if enabled:
            try:
                saved = AutomaticMemory(path, self.cfg.agent.memory_retention)
                history = saved.recent(session_id, self.cfg.agent.history_turns)
                background = json.dumps({"memory": json.loads(saved.context(query)),
                                         "recent_conversation": [
                                             {**m, "content": m["content"][:1000]} for m in history[-8:]]}, ensure_ascii=False)
            except Exception as exc:
                warnings.warn(f"Memory read failed: {exc}", RuntimeWarning)
        with memory_context(path, bool(enabled), background) as calls:
            try:
                result = self._ask(query, agent, bool(enabled), stream, on_token, trace_name,
                                   extra_meta, history)
            except Exception as exc:
                if saved is not None and self.cfg.agent.auto_memory:
                    try:
                        saved.remember(session_id, query, f"Execution failed: {exc}", calls, "error")
                    except Exception as err:
                        warnings.warn(f"Memory write failed: {err}", RuntimeWarning)
                raise
            if saved is not None and self.cfg.agent.auto_memory:
                outcome = ("cancelled" if result.metadata.get("cancelled") else
                           "incomplete" if result.metadata.get("max_turns_exceeded") else
                           "tool_errors" if any(not c["success"] for c in calls) else
                           "tools_ok" if calls else "unverified_reply")
                try:
                    saved.remember(session_id, query, result.content, calls, outcome)
                    result.metadata["memory_saved"] = True
                except Exception as exc:
                    result.metadata["memory_saved"] = False
                    warnings.warn(f"Memory write failed: {exc}", RuntimeWarning)
            result.metadata["session_id"] = session_id
            return result

    def _ask(self, query: str, agent: Optional[str] = None,
             memory: bool = True, stream: bool = False, on_token: Any = None,
             trace_name: str = "ask", extra_meta: Optional[Dict[str, str]] = None,
             history: Optional[List[Dict[str, str]]] = None) -> Any:
        """یک سؤال → AgentResult. (با trace، کنترل لغو، بلک‌برد مشترک و استریم اختیاری)"""
        from ultimate_khorshid.agents.base import AgentContext, AgentResult
        from ultimate_khorshid.core.blackboard import Blackboard, use_board
        from ultimate_khorshid.core.control import CancelledError, RunController, current_controller, use_controller
        from ultimate_khorshid.core.tracing import Tracer, use_tracer
        use_mem = self.cfg.agent.context_from_memory if memory is None else memory
        mem_hits: List[Any] = []
        if use_mem:
            try:
                from ultimate_khorshid.memory.store import get_memory
                mem_hits = get_memory().search(query, 4)
            except Exception:
                pass
        tracer, ctrl, board = Tracer(), current_controller() or RunController(), Blackboard()
        self.last_controller, self.last_board = ctrl, board
        tid = tracer.start_trace(trace_name, {"agent": agent or self.cfg.agent.default_agent,
                                              "q": query[:200], "stream": bool(stream)})
        self.last_trace_id = tid
        conv = Conversation()
        for message in history or []:
            conv.add(message["role"], message["content"])
        conv.add("user", query)
        meta: Dict[str, Any] = {"stream": bool(stream)}
        if extra_meta:
            meta.update(extra_meta)
        ctx = AgentContext(conversation=conv, tools=self.tool_names, memory_results=mem_hits,
                           metadata=meta)
        if on_token is not None:
            ctx.metadata["on_token"] = on_token
        from ultimate_khorshid.tools.mt5_demo import direct_command
        direct_action = direct_command(query)
        ag = self.build_agent(agent) if direct_action is None else None
        from ultimate_khorshid.agents.base import stream_sink_ctx, provider_trace_ctx
        with use_tracer(tracer, tid), use_controller(ctrl), use_board(board), \
                stream_sink_ctx(on_token), provider_trace_ctx() as providers:
            try:
                ctrl.check()
                if direct_action is not None:
                    import json
                    from ultimate_khorshid.core.types import ToolCall
                    tr = self.executor.execute(ToolCall(
                        name="mt5_demo", arguments=json.dumps({"action": direct_action})))
                    result = AgentResult(content=tr.metadata.get("summary", tr.content),
                                         tool_results=[tr],
                                         metadata={"agent": "demo-controller", "model": "deterministic"})
                else:
                    result = ag.run(ctx)
                ctrl.check()
                tracer.end_trace(tid, "ok")
            except CancelledError as e:
                tracer.end_trace(tid, "cancelled")
                return AgentResult(content=f"⏹ {e}", metadata={"cancelled": True, "trace_id": tid})
            except Exception:
                tracer.end_trace(tid, "error")
                raise
        try:
            result.metadata["trace_id"] = tid
            if providers:
                final = providers[-1]
                result.metadata.update(engine=final['engine'], model=final['model'],
                                       fallback=final['fallback'], provider_calls=providers,
                                       usage={'input_tokens':sum(p['input_tokens'] for p in providers),
                                              'output_tokens':sum(p['output_tokens'] for p in providers),
                                              'estimated':any(p['input_estimated'] or p['output_estimated'] for p in providers)})
        except Exception:
            pass
        return result

    def chat_loop(self, agent: Optional[str] = None) -> None:
        print("🤖 خورشید نهایی — برای خروج بنویسید: exit / خروج\n")
        while True:
            try:
                q = input("شما: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\nخدانگهدار قربان. 👋")
                break
            if q.lower() in ("exit", "quit", "خروج", "خداحافظ"):
                print("خدانگهدار قربان. 👋")
                break
            if not q:
                continue
            try:
                r = self.ask(q, agent=agent)
            except Exception as e:
                print(f"❌ خطا: {e}\n")
                continue
            print(f"\nخورشید:\n{r.content}\n")


def ask(query: str, agent: str = "computer", config: Optional[str] = None) -> str:
    rt = KhorshidRuntime(load_config(config) if config else None)
    try:
        return rt.ask(query, agent=agent).content
    finally:
        rt.executor.shutdown()


def list_agents() -> List[str]:
    _ensure_imports()
    return sorted(AgentRegistry.keys())


def list_tools() -> Dict[str, str]:
    _ensure_imports()
    out = {}
    for name, cls in ToolRegistry.items():
        try:
            out[name] = cls().spec.description[:100]
        except Exception:
            out[name] = "?"
    return out

