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


TOOL_MODULES = ("essentials", "files", "shell", "web", "system", "memory_tools",
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
                 interactive: bool = False) -> None:
        from ultimate_khorshid.engine.discovery import engine_for_model
        from ultimate_khorshid.tools.base import ToolExecutor
        from ultimate_khorshid.skills.manager import SkillManager

        _ensure_imports()
        self.cfg = cfg or load_config()
        try:
            from ultimate_khorshid.core.settings import apply_to_config
            apply_to_config(self.cfg)  # اورلی تنظیمات داشبورد (engine/model/voice)
        except Exception:
            pass
        self.bus = EventBus()
        self.model = self.cfg.intelligence.default_model
        self.engine = engine_for_model(self.model, self.cfg)

        # ابزارها
        wanted = (self.cfg.agent.tools or "*").strip()
        tools = []
        for name, cls in ToolRegistry.items():
            if wanted not in ("*", "all") and name not in [w.strip() for w in wanted.split(",")]:
                continue
            try:
                tools.append(cls())
            except Exception:
                pass
        self.executor = ToolExecutor(tools, bus=self.bus, interactive=interactive,
                                     confirm_callback=confirm_callback)
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
        try:
            return cls(self.engine, self.model, bus=self.bus,
                       temperature=self.cfg.intelligence.temperature,
                       max_tokens=self.cfg.intelligence.max_tokens,
                       system_prompt=sys_prompt, max_turns=self.cfg.agent.max_turns,
                       executor=self.executor)
        except TypeError:
            return cls(self.engine, self.model, bus=self.bus,
                       temperature=self.cfg.intelligence.temperature,
                       max_tokens=self.cfg.intelligence.max_tokens,
                       system_prompt=sys_prompt, max_turns=self.cfg.agent.max_turns)

    def ask(self, query: str, agent: Optional[str] = None,
            memory: bool | None = None, stream: bool = False,
            on_token: Any = None, trace_name: str = "ask",
            extra_meta: Optional[Dict[str, str]] = None) -> Any:
        """یک سؤال → AgentResult. (با trace، کنترل لغو، بلک‌برد مشترک و استریم اختیاری)"""
        from ultimate_khorshid.agents.base import AgentContext, AgentResult
        from ultimate_khorshid.core.blackboard import Blackboard, use_board
        from ultimate_khorshid.core.control import CancelledError, RunController, use_controller
        from ultimate_khorshid.core.tracing import Tracer, use_tracer
        use_mem = self.cfg.agent.context_from_memory if memory is None else memory
        mem_hits: List[Any] = []
        if use_mem:
            try:
                from ultimate_khorshid.memory.store import get_memory
                mem_hits = get_memory(self.cfg.storage.db_path).search(query, 4)
            except Exception:
                pass
        tracer, ctrl, board = Tracer(), RunController(), Blackboard()
        self.last_controller, self.last_board = ctrl, board
        tid = tracer.start_trace(trace_name, {"agent": agent or self.cfg.agent.default_agent,
                                              "q": query[:200], "stream": bool(stream)})
        self.last_trace_id = tid
        conv = Conversation()
        conv.add("user", query)
        meta: Dict[str, Any] = {"stream": bool(stream)}
        if extra_meta:
            meta.update(extra_meta)
        ctx = AgentContext(conversation=conv, tools=self.tool_names, memory_results=mem_hits,
                           metadata=meta)
        if on_token is not None:
            ctx.metadata["on_token"] = on_token
        ag = self.build_agent(agent)
        from ultimate_khorshid.agents.base import stream_sink_ctx
        with use_tracer(tracer, tid), use_controller(ctrl), use_board(board), \
                stream_sink_ctx(on_token):
            try:
                result = ag.run(ctx)
                tracer.end_trace(tid, "ok")
            except CancelledError as e:
                tracer.end_trace(tid, "cancelled")
                return AgentResult(content=f"⏹ {e}", metadata={"cancelled": True, "trace_id": tid})
            except Exception:
                tracer.end_trace(tid, "error")
                raise
        try:
            result.metadata["trace_id"] = tid
        except Exception:
            pass
        return result

    def chat_loop(self, agent: Optional[str] = None) -> None:
        from ultimate_khorshid.agents.base import AgentContext
        print("🤖 خورشید نهایی — برای خروج بنویسید: exit / خروج\n")
        conv = Conversation()
        ag = self.build_agent(agent)
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
            conv.add("user", q)
            ctx = AgentContext(conversation=conv, tools=self.tool_names)
            try:
                r = ag.run(ctx)
            except Exception as e:
                print(f"❌ خطا: {e}\n")
                continue
            conv.add("assistant", r.content)
            print(f"\nخورشید:\n{r.content}\n")
            try:  # sliding window: چت‌های طولانی حافظه را منفجر نکنند
                from ultimate_khorshid.core import context as Ctx
                ds = [m.to_dict() for m in conv.messages]
                kept, dropped, _ = Ctx.trim_messages(ds, Ctx.DEFAULT_BUDGET * 2)
                if dropped:
                    conv = Conversation()
                    for d in kept:
                        conv.add(d.get("role", "user"), str(d.get("content", "")))
                    print(f"(🧹 {dropped} پیام قدیمی از پنجره چت خارج شد)\n")
            except Exception:
                pass


def ask(query: str, agent: str = "computer", config: Optional[str] = None) -> str:
    rt = KhorshidRuntime(load_config(config) if config else None)
    return rt.ask(query, agent=agent).content


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
