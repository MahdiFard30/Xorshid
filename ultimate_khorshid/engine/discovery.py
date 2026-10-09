"""Engine discovery — ساخت موتور از روی کانفیگ/مدل."""

from __future__ import annotations

from ultimate_khorshid.core.config import KhorshidConfig
from ultimate_khorshid.core.registry import EngineRegistry
from ultimate_khorshid.engine.base import InferenceEngine

# ایمپورت برای رجیستر شدن — مهم!
import importlib

for _mod in ("mock", "ollama", "openai_compat", "gemini"):
    importlib.import_module(f"ultimate_khorshid.engine.{_mod}")


def get_engine(name: str, cfg: KhorshidConfig | None = None) -> InferenceEngine:
    name = (name or "mock").lower()
    if name == "mock":
        return EngineRegistry.create("mock")
    if name == "ollama":
        host = cfg.engine.ollama_host if cfg else ""
        return EngineRegistry.create("ollama", host=host or "http://localhost:11434")
    if name in ("gemini", "google"):
        key = (cfg.engine.gemini_api_key if cfg else "") or ""
        return EngineRegistry.create("gemini", api_key=key)
    if name in ("openai", "openai_compat", "deepseek", "openrouter", "vllm", "lmstudio"):
        key = cfg.engine.openai_api_key if cfg else ""
        base = cfg.engine.openai_base_url if cfg else "https://api.openai.com/v1"
        real = "openai_compat" if EngineRegistry.contains("openai_compat") else "openai"
        return EngineRegistry.create(real, api_key=key, base_url=base)
    if EngineRegistry.contains(name):
        return EngineRegistry.create(name)
    raise KeyError(f"Unknown engine '{name}'. Available: {sorted(EngineRegistry.keys())}")


def engine_for_model(model_id: str, cfg: KhorshidConfig | None = None) -> InferenceEngine:
    from ultimate_khorshid.intelligence.catalog import resolve_model
    spec = resolve_model(model_id)
    return get_engine(spec.engine, cfg)
