"""Checkpoint — ذخیره/بازیابی وضعیت اجراهای چندمرحله‌ای (resume بعد از کرش)."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


def default_dir() -> Path:
    p = Path(os.path.expanduser("~/.ultimate-jarvis/checkpoints"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _dir(base: Optional[str]) -> Path:
    p = Path(os.path.expanduser(base)) if base else default_dir()
    p.mkdir(parents=True, exist_ok=True)
    return p


def save(run_id: str, state: Dict[str, Any], base: Optional[str] = None) -> Path:
    state = dict(state)
    state["_run_id"] = run_id
    state["_saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    fp = _dir(base) / f"{run_id}.json"
    fp.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")
    return fp


def load(run_id: str, base: Optional[str] = None) -> Optional[Dict[str, Any]]:
    fp = _dir(base) / f"{run_id}.json"
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception:
        return None


def list_runs(base: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    for fp in sorted(_dir(base).glob("*.json")):
        try:
            d = json.loads(fp.read_text(encoding="utf-8"))
            out.append({"id": fp.stem, "saved_at": d.get("_saved_at", "?"),
                        "keys": [k for k in d if not k.startswith("_")]})
        except Exception:
            pass
    return out


def clear(run_id: Optional[str] = None, base: Optional[str] = None) -> int:
    d = _dir(base)
    if run_id:
        fp = d / f"{run_id}.json"
        try:
            fp.unlink(missing_ok=True)
            return 1
        except Exception:
            return 0
    n = 0
    for fp in d.glob("*.json"):
        try:
            fp.unlink()
            n += 1
        except Exception:
            pass
    return n
