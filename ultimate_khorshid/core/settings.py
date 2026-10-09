"""settings.json — تنظیمات قابل تغییر از داشبورد/CLI (روی TOML سوار می‌شود).

کلیدها: hotkey, hotkey_action, engine, model, voice
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

DEFAULTS: Dict[str, str] = {
    "hotkey": "ctrl",
    "hotkey_action": "voice",  # voice | dashboard
    "engine": "",
    "model": "",
    "voice": "Kore",
}


def settings_path() -> Path:
    p = Path.home() / ".ultimate-jarvis" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def get_settings() -> Dict[str, str]:
    out = dict(DEFAULTS)
    fp = settings_path()
    if fp.exists():
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            for k in DEFAULTS:
                if data.get(k):
                    out[k] = str(data[k])
        except Exception:
            pass
    return out


def set_settings(**kw: Any) -> Dict[str, str]:
    out = get_settings()
    for k, v in kw.items():
        if k in DEFAULTS and v:
            out[k] = str(v)
    settings_path().write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def apply_to_config(cfg: Any) -> Any:
    """اورلی تنظیمات داشبورد روی کانفیگ (engine/model/voice)."""
    s = get_settings()
    try:
        if s.get("engine"):
            cfg.engine.default = s["engine"]
            cfg.intelligence.preferred_engine = s["engine"]
        if s.get("model"):
            cfg.intelligence.default_model = s["model"]
        if s.get("voice"):
            cfg.engine.voice = s["voice"]
    except Exception:
        pass
    return cfg
