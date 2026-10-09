"""Decorator-based registry for runtime discovery — قلب معماری خورشید.

الگو گرفته از OpenJarvis (RegistryBase[T]) — هر کامپوننت با یک دکوراتور
قابل کشف می‌شود و نیازی به تغییر factory نیست:

    @ToolRegistry.register("my_tool")
    class MyTool(BaseTool): ...
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Generic, Tuple, Type, TypeVar

T = TypeVar("T")


class RegistryBase(Generic[T]):
    """Generic registry base with per-class isolated storage."""

    @classmethod
    def _entries(cls) -> Dict[str, T]:
        attr = f"_registry_entries_{cls.__name__}"
        storage = getattr(cls, attr, None)
        if storage is None:
            storage = {}
            setattr(cls, attr, storage)
        return storage

    @classmethod
    def register(cls, key: str) -> Callable[[T], T]:
        def deco(entry: T) -> T:
            entries = cls._entries()
            if key in entries:
                raise ValueError(f"{cls.__name__} already has entry '{key}'")
            entries[key] = entry
            return entry

        return deco

    @classmethod
    def register_value(cls, key: str, value: T) -> T:
        entries = cls._entries()
        if key in entries:
            raise ValueError(f"{cls.__name__} already has entry '{key}'")
        entries[key] = value
        return value

    @classmethod
    def get(cls, key: str) -> T:
        try:
            return cls._entries()[key]
        except KeyError as exc:
            raise KeyError(
                f"{cls.__name__} has no entry '{key}'. Available: {sorted(cls._entries())}"
            ) from exc

    @classmethod
    def create(cls, key: str, *args: Any, **kwargs: Any) -> Any:
        entry = cls.get(key)
        if not callable(entry):
            raise TypeError(f"Entry '{key}' is not callable")
        return entry(*args, **kwargs)

    @classmethod
    def items(cls) -> Tuple[Tuple[str, T], ...]:
        return tuple(cls._entries().items())

    @classmethod
    def keys(cls) -> Tuple[str, ...]:
        return tuple(cls._entries().keys())

    @classmethod
    def contains(cls, key: str) -> bool:
        return key in cls._entries()

    @classmethod
    def clear(cls) -> None:
        cls._entries().clear()


class ModelRegistry(RegistryBase[Any]):
    """ModelSpec objects."""


class EngineRegistry(RegistryBase[Type[Any]]):
    """Inference engine backends (mock, ollama, openai_compat, ...)."""


class MemoryRegistry(RegistryBase[Type[Any]]):
    """Memory backends."""


class AgentRegistry(RegistryBase[Type[Any]]):
    """Agent implementations."""


class ToolRegistry(RegistryBase[Any]):
    """Tool implementations."""


class RouterPolicyRegistry(RegistryBase[Any]):
    """Router policies."""


class ChannelRegistry(RegistryBase[Any]):
    """Channel implementations (cli, telegram, ...)."""


class SkillRegistry(RegistryBase[Any]):
    """Skill manifests."""


class BenchmarkRegistry(RegistryBase[Any]):
    """Benchmark implementations."""
