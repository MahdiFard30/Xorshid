"""Model catalog — کاتالوگ مدل‌ها (لوکال + ابری)."""

from __future__ import annotations

from typing import List
from ultimate_khorshid.core.registry import ModelRegistry
from ultimate_khorshid.core.types import ModelSpec

BUILTIN_MODELS: List[ModelSpec] = [
    ModelSpec(id="mock/smart", engine="mock", supports_tools=True, local=True,
              description="موتور آفلاین داخلی — بدون نیاز به اینترنت/API، مناسب تست و کارهای دترمینیستیک"),
    ModelSpec(id="ollama/llama3.1:8b", aliases=["llama3.1:8b"], engine="ollama",
              parameters_b=8, context_window=128000, supports_tools=True, local=True,
              description="Llama 3.1 لوکال via Ollama"),
    ModelSpec(id="ollama/qwen2.5:7b", aliases=["qwen2.5:7b"], engine="ollama",
              parameters_b=7.5, context_window=32768, supports_tools=True, local=True,
              description="Qwen 2.5 لوکال via Ollama — عالی برای فارسی و کد"),
    ModelSpec(id="openai/gpt-4o-mini", aliases=["gpt-4o-mini"], engine="openai_compat",
              context_window=128000, supports_tools=True, local=False,
              description="GPT-4o mini ابری — سریع و ارزان"),
    ModelSpec(id="openai/gpt-4o", aliases=["gpt-4o"], engine="openai_compat",
              context_window=128000, supports_tools=True, local=False,
              description="GPT-4o ابری — قوی‌ترین عمومی"),
    ModelSpec(id="deepseek/deepseek-chat", aliases=["deepseek-chat"], engine="openai_compat",
              context_window=64000, supports_tools=True, local=False,
              description="DeepSeek Chat — عالی برای کد (با base_url مناسب)"),
    ModelSpec(id="gemini/gemini-2.0-flash", aliases=["gemini-2.0-flash", "gemini-flash"], engine="gemini",
              context_window=1000000, supports_tools=True, local=False,
              description="Gemini 2.0 Flash — سریع، فارسی عالی، function calling (کلید رایگان از AI Studio)"),
    ModelSpec(id="gemini/gemini-2.5-flash", aliases=["gemini-2.5-flash"], engine="gemini",
              context_window=1000000, supports_tools=True, local=False,
              description="Gemini 2.5 Flash — نسل جدید، استدلال قوی‌تر"),
]


def _register_builtins() -> None:
    for m in BUILTIN_MODELS:
        try:
            ModelRegistry.register_value(m.id, m)
        except ValueError:
            pass
        for a in m.aliases:
            try:
                ModelRegistry.register_value(a, m)
            except ValueError:
                pass


_register_builtins()


def resolve_model(model_id: str) -> ModelSpec:
    if ModelRegistry.contains(model_id):
        return ModelRegistry.get(model_id)
    # حدس موتور از روی پیشوند
    if model_id.startswith("ollama/") or ":" in model_id:
        return ModelSpec(id=model_id, engine="ollama", supports_tools=True, local=True)
    if model_id.startswith("mock/"):
        return ModelSpec(id=model_id, engine="mock", supports_tools=True, local=True)
    if model_id.startswith("gemini/") or model_id.startswith("gemini-"):
        return ModelSpec(id=model_id, engine="gemini", supports_tools=True, local=False)
    return ModelSpec(id=model_id, engine="openai_compat", supports_tools=True, local=False)
