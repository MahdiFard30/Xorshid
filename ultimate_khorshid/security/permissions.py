"""Action-level approval policy shared by every tool entry point.

This is an approval boundary, not an OS sandbox. Unknown third-party tools must
declare requires_confirmation when they can change external state.
"""
from typing import Any, Mapping


def approval_required(spec: Any, params: Mapping[str, Any]) -> bool:
    name = spec.name
    if spec.requires_confirmation:
        return True
    if name in {"mt5_demo", "mt5_multi_worker"}:
        # Emergency stop must remain available even without a UI.
        return params.get("action") not in {"status", "report", "catalog", "stop"}
    if name == "mt5_read":
        return False
    if name == "git":
        return params.get("action", "status").lower() not in {"status", "log", "diff"}
    if name == "http_request":
        return str(params.get("method", "GET")).upper() not in {"GET", "HEAD", "OPTIONS"}
    if name == "clipboard":
        return params.get("action", "get") == "set"
    return name in {
        "shell_exec", "python_exec", "file_write", "file_edit", "file_delete",
        "file_copy", "file_move", "mouse_click", "key_press", "key_hotkey",
        "type_text", "vision_click", "browser_click", "browser_type",
        "browser_press", "browser_check", "browser_select_option",
    }
