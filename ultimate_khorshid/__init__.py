"""ULTIMATE KHORSHID — قدرتمندترین ایجنت کامپیوتری پایتونی.

الهام‌گرفته از معماری OpenJarvis استنفورد (۵ ستون: Intelligence / Engine / Agents / Tools+Memory / Learning)
با تمرکز بر «کامپیوتر ایجنت» که واقعاً هر کاری انجام می‌دهد: فایل، شل، وب، کد، حافظه، زمان‌بندی، سرور و...
"""

__version__ = "2.0.0"
__author__ = "Ultimate Jarvis"

# Compatibility with existing environment overrides; never prints values.
import os as _os
for _key, _value in list(_os.environ.items()):
    if _key.startswith("UJARVIS_"):
        _os.environ.setdefault("KHORSHID_" + _key[len("UJARVIS_"):], _value)

from ultimate_khorshid.core.registry import (
    AgentRegistry,
    ChannelRegistry,
    EngineRegistry,
    MemoryRegistry,
    SkillRegistry,
    ToolRegistry,
)

__all__ = [
    "__version__",
    "AgentRegistry",
    "EngineRegistry",
    "ToolRegistry",
    "MemoryRegistry",
    "ChannelRegistry",
    "SkillRegistry",
]
