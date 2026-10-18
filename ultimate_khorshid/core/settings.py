"""settings.json — تنظیمات قابل تغییر از داشبورد/CLI (روی TOML سوار می‌شود).

کلیدها: hotkey, hotkey_action, engine, model, voice
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, str] = {
    "hotkey": "ctrl",
    "hotkey_action": "voice",  # voice | dashboard
    "engine": "",
    "model": "",
    "voice": "",  # Empty means inherit the resolved TOML/environment voice.
}
_write_lock = threading.RLock()


def _stored() -> Dict[str, str]:
    try:
        data = json.loads(settings_path().read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        return {k: str(v) for k, v in data.items() if k in DEFAULTS and isinstance(v, str)}
    except (OSError, ValueError):
        return {}


def settings_path() -> Path:
    p = Path.home() / ".ultimate-jarvis" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_settings() -> Dict[str, str]:
    out = dict(DEFAULTS)
    out.update(_stored())
    return out


def set_settings(**kw: Any) -> Dict[str, str]:
    with _write_lock:
        # Persist overrides, not UI defaults: absent voice must not mask TOML.
        out = _stored()
        for k, v in kw.items():
            if k in DEFAULTS and v is not None:
                value = str(v).strip()
                out[k] = value if value or k in {"engine", "model", "voice"} else DEFAULTS[k]
        if out.get("engine") and out["engine"] not in {"mock", "ollama", "gemini", "openai", "openai_compat"}:
            raise ValueError("Unsupported engine")
        if "engine" in kw and "model" not in kw:
            out["model"] = ""  # Previous provider's model must not defeat a new engine choice.
        if out.get("engine") and out.get("model"):
            from ultimate_khorshid.intelligence.catalog import resolve_model
            engine = {"openai": "openai_compat"}.get(out["engine"], out["engine"])
            if resolve_model(out["model"]).engine != engine:
                raise ValueError("مدل با موتور انتخاب‌شده هماهنگ نیست؛ مدل را اصلاح یا خالی کنید.")
        fp = settings_path()
        fp.parent.mkdir(parents=True, exist_ok=True)
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=fp.parent, delete=False) as tmp:
                temp_path = Path(tmp.name)
                json.dump(out, tmp, ensure_ascii=False, indent=1)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(temp_path, fp)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
        return {**DEFAULTS, **out}


def apply_to_config(cfg: Any) -> Any:
    """اورلی تنظیمات داشبورد روی کانفیگ (engine/model/voice)."""
    s = _stored()
    if s.get("engine") and not s.get("model"):
        from ultimate_khorshid.core.config import select_engine
        select_engine(cfg, s["engine"])
    if s.get("model"):
        cfg.intelligence.default_model = s["model"]
    if s.get("voice"):
        cfg.engine.voice = s["voice"]
    return cfg
