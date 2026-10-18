"""Config — بارگذاری TOML + override با متغیر محیطی. (فقط stdlib)"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import tomllib  # py3.11+
except ImportError:  # pragma: no cover
    try:
        import tomli as tomllib  # Python 3.10 optional compatibility dependency
    except ImportError:
        tomllib = None  # type: ignore

DEFAULT_CONFIG_PATHS = [
    Path.home() / ".ultimate-jarvis" / "config.toml",
    Path("configs/default.toml"),
    Path(__file__).resolve().parents[2] / "configs" / "default.toml",
]


@dataclass(slots=True)
class IntelligenceConfig:
    default_model: str = "mock/smart"
    fallback_model: str = "mock/smart"
    preferred_engine: str = "mock"
    provider: str = "local"
    temperature: float = 0.7
    max_tokens: int = 1024
    top_p: float = 0.9


@dataclass(slots=True)
class AgentSectionConfig:
    default_agent: str = "computer"
    max_turns: int = 12
    tools: str = "*"  # * = همه ابزارها
    objective: str = "به کاربر کمک کن؛ فارسی روان حرف بزن."
    context_from_memory: bool = True
    auto_memory: bool = True
    history_turns: int = 8
    memory_retention: int = 1000
    persona: str = "khorshid"
    language: str = "fa"


@dataclass(slots=True)
class EngineSectionConfig:
    default: str = "mock"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-120b"
    gemini_tts_model: str = "gemini-2.5-flash-preview-tts"
    voice: str = "Kore"


@dataclass(slots=True)
class ToolsConfig:
    confirm_dangerous: bool = True
    sandbox_shell: bool = False
    workspace: str = "~/ultimate-jarvis-workspace"


@dataclass(slots=True)
class StorageConfig:
    default_backend: str = "sqlite"
    db_path: str = "~/.ultimate-jarvis/memory.db"


@dataclass(slots=True)
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8899
    agent: str = "computer"


@dataclass(slots=True)
class KhorshidConfig:
    intelligence: IntelligenceConfig = field(default_factory=IntelligenceConfig)
    agent: AgentSectionConfig = field(default_factory=AgentSectionConfig)
    engine: EngineSectionConfig = field(default_factory=EngineSectionConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    server: ServerConfig = field(default_factory=ServerConfig)
    raw: Dict[str, Any] = field(default_factory=dict)


def _merge_dataclass(dc: Any, data: Dict[str, Any]) -> Any:
    for k, v in data.items():
        if hasattr(dc, k):
            try:
                setattr(dc, k, v)
            except Exception:
                pass
    return dc


def load_config(path: Optional[str | Path] = None) -> KhorshidConfig:
    """TOML < saved dashboard preferences < ENV; explicit files skip preferences.

    Explicit file paths (including KHORSHID_CONFIG) never silently fall back.
    A caller-supplied KhorshidConfig is already resolved and Runtime leaves it alone.
    """
    cfg = KhorshidConfig()
    candidates: List[Path] = []
    explicit = path or os.environ.get("KHORSHID_CONFIG")
    if explicit:
        candidates.append(Path(explicit).expanduser())
    else:
        candidates.extend(DEFAULT_CONFIG_PATHS)
    data: Dict[str, Any] = {}
    for c in candidates:
        if not c.exists():
            if explicit:
                raise FileNotFoundError(f"Config file not found: {c}")
            continue
        if tomllib is None:
            raise RuntimeError("Python 3.10 needs tomli to read config: pip install -e .")
        try:
            data = tomllib.loads(c.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            raise ValueError(f"Cannot read config: {c} ({type(exc).__name__})") from None
        break
    if data:
        cfg.raw = data
        if "intelligence" in data:
            _merge_dataclass(cfg.intelligence, data["intelligence"])
        if "agent" in data:
            _merge_dataclass(cfg.agent, data["agent"])
        if "engine" in data:
            eng = dict(data["engine"])
            # تخت‌سازی زیربخش‌ها مثل [engine.ollama]
            for sub in ("ollama", "openai", "openai_compat", "gemini", "groq"):
                if sub in eng and isinstance(eng[sub], dict):
                    for k, v in eng[sub].items():
                        if sub == 'groq' and k in ('api_key', 'model'):
                            setattr(cfg.engine, 'groq_' + k, v)
                        elif sub == "ollama" and k == "host":
                            cfg.engine.ollama_host = v
                        elif sub == "ollama" and k == "model":
                            cfg.engine.ollama_model = v
                        elif sub == "gemini" and k == "api_key":
                            cfg.engine.gemini_api_key = v
                        elif sub == "gemini" and k == "model":
                            cfg.engine.gemini_model = v
                        elif sub == "gemini" and k == "tts_model":
                            cfg.engine.gemini_tts_model = v
                        elif sub == "gemini" and k == "voice":
                            cfg.engine.voice = v
                        elif k in ("api_key",):
                            cfg.engine.openai_api_key = v
                        elif k in ("base_url", "host"):
                            cfg.engine.openai_base_url = v
                        elif k == "model":
                            cfg.engine.openai_model = v
                    del eng[sub]
            _merge_dataclass(cfg.engine, eng)
        if "tools" in data and isinstance(data["tools"], dict):
            t = dict(data["tools"])
            t.pop("storage", None)
            t.pop("mcp", None)
            _merge_dataclass(cfg.tools, t)
        if "tools" in data and "storage" in data["tools"]:
            _merge_dataclass(cfg.storage, data["tools"]["storage"])
        if "storage" in data:
            _merge_dataclass(cfg.storage, data["storage"])
        if "server" in data:
            _merge_dataclass(cfg.server, data["server"])

    if not explicit:
        from ultimate_khorshid.core.settings import apply_to_config
        apply_to_config(cfg)
    apply_environment(cfg)
    return cfg


def select_engine(cfg: KhorshidConfig, engine: str) -> None:
    """An engine-only choice also selects its configured provider model."""
    engine = {"openai": "openai_compat", "google": "gemini"}.get(engine, engine)
    models = {"mock": "mock/smart", "ollama": "ollama/" + cfg.engine.ollama_model,
              "gemini": "gemini/" + cfg.engine.gemini_model,
              "groq": "groq/" + cfg.engine.groq_model,
              "openai_compat": "openai/" + cfg.engine.openai_model}
    if engine not in models:
        raise ValueError(f"Unsupported engine: {engine}")
    cfg.engine.default = cfg.intelligence.preferred_engine = engine
    cfg.intelligence.default_model = models[engine]


def apply_environment(cfg: KhorshidConfig) -> None:
    # ENV always has the final word, including saved dashboard preferences.
    e = os.environ.get
    if e('GROQ_API_KEY'):
        cfg.engine.groq_api_key = e('GROQ_API_KEY')
    if e('KHORSHID_GROQ_MODEL'):
        cfg.engine.groq_model = e('KHORSHID_GROQ_MODEL')
    if e("OPENAI_API_KEY") and not cfg.engine.openai_api_key:
        cfg.engine.openai_api_key = e("OPENAI_API_KEY", "")
    gkey = e("GEMINI_API_KEY") or e("GOOGLE_API_KEY")
    if gkey and not cfg.engine.gemini_api_key:
        cfg.engine.gemini_api_key = gkey
    if e("KHORSHID_VOICE"):
        cfg.engine.voice = e("KHORSHID_VOICE") or cfg.engine.voice
    if e("OPENAI_BASE_URL"):
        cfg.engine.openai_base_url = e("OPENAI_BASE_URL") or cfg.engine.openai_base_url
    if e("KHORSHID_OPENAI_MODEL"):
        cfg.engine.openai_model = e("KHORSHID_OPENAI_MODEL") or cfg.engine.openai_model
    if e("OLLAMA_HOST"):
        cfg.engine.ollama_host = e("OLLAMA_HOST") or cfg.engine.ollama_host
    if e("KHORSHID_AGENT"):
        cfg.agent.default_agent = e("KHORSHID_AGENT") or cfg.agent.default_agent
    if e("KHORSHID_LANG"):
        cfg.agent.language = e("KHORSHID_LANG") or cfg.agent.language
    if e("KHORSHID_ENGINE"):
        select_engine(cfg, e("KHORSHID_ENGINE", ""))
    if e("KHORSHID_MODEL"):
        cfg.intelligence.default_model = e("KHORSHID_MODEL", "")
    from ultimate_khorshid.intelligence.catalog import resolve_model
    actual = resolve_model(cfg.intelligence.default_model).engine
    cfg.engine.default = cfg.intelligence.preferred_engine = actual


def ensure_dirs(cfg: KhorshidConfig) -> Dict[str, Path]:
    base = Path.home() / ".ultimate-jarvis"
    ws = Path(cfg.tools.workspace).expanduser()
    base.mkdir(parents=True, exist_ok=True)
    ws.mkdir(parents=True, exist_ok=True)
    Path(cfg.storage.db_path).expanduser().parent.mkdir(parents=True, exist_ok=True)
    return {"base": base, "workspace": ws}

