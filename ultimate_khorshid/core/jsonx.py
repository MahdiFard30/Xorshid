"""JSON مقاوم — تعمیر خروجی خراب LLM + اعتبارسنجی schema سبک (stdlib).

parse_strict(text, schema): استخراج → تعمیر → اعتبارسنجی → (obj, errors)
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


def _strip_fences(text: str) -> str:
    t = text.strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", t)
    if m:
        return m.group(1).strip()
    return t


def _balanced_slice(text: str) -> str:
    """اولین آبجکت/آرایه متوازن از متن (برای JSON ناقص، تا حد ممکن)."""
    start = -1
    opens: Dict[str, str] = {"{": "}", "[": "]"}
    stack: List[str] = []
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch in opens:
            if start < 0:
                start = i
            stack.append(opens[ch])
        elif ch in ("}", "]"):
            if stack and ch == stack[-1]:
                stack.pop()
                if not stack and start >= 0:
                    return text[start:i + 1]
            elif start >= 0:
                break  # براکت اضافه: همان‌جا ببر
    if start >= 0:
        frag = text[start:]
        frag += "".join(reversed(stack))  # بستن ناقصی‌ها
        return frag
    return text


def repair_json(text: str) -> str:
    t = _strip_fences(text)
    t = _balanced_slice(t)
    t = re.sub(r",\s*([}\]])", r"\1", t)  # کامای اضافی آخر
    return t.strip()


def parse_loose(text: str) -> Any:
    """پارس مقاوم: مستقیم → تعمیرشده. خطا: ValueError با پیام فارسی."""
    try:
        return json.loads(text)
    except Exception:
        pass
    fixed = repair_json(text)
    try:
        return json.loads(fixed)
    except Exception as e:
        raise ValueError(f"JSON نامعتبر حتی بعد از تعمیر: {e}")


def validate_schema(obj: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """اعتبارسنج مینی‌مال: type/required/properties/enum/items/minimum/maximum."""
    errs: List[str] = []
    t = schema.get("type")
    if t:
        ok = {"string": str, "integer": int, "number": (int, float),
              "boolean": bool, "object": dict, "array": list,
              "null": type(None)}.get(t)
        if ok is not None and not isinstance(obj, ok):
            errs.append(f"{path}: انتظار {t} بود")
            return errs
    if isinstance(obj, dict):
        for req in schema.get("required", []) or []:
            if req not in obj:
                errs.append(f"{path}: فیلد لازم «{req}» نیست")
        props = schema.get("properties", {}) or {}
        for k, v in obj.items():
            if k in props:
                errs += validate_schema(v, props[k], f"{path}.{k}")
    if isinstance(obj, list) and "items" in schema:
        for i, v in enumerate(obj[:50]):
            errs += validate_schema(v, schema["items"], f"{path}[{i}]")
    if "enum" in schema and obj not in schema["enum"]:
        errs.append(f"{path}: مقدار باید یکی از {schema['enum']} باشد")
    return errs


def parse_strict(text: str, schema: Optional[Dict[str, Any]] = None) -> Tuple[Any, List[str]]:
    """(آبجکت، خطاهای schema). خطای پارس → raise."""
    obj = parse_loose(text)
    errs = validate_schema(obj, schema) if schema else []
    return obj, errs
