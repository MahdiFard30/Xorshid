"""JSON مقاوم — تعمیر خروجی خراب LLM + اعتبارسنجی schema سبک (stdlib).

parse_strict(text, schema): استخراج → تعمیر → اعتبارسنجی → (obj, errors)
"""

from __future__ import annotations

import json
import math
import re
from fractions import Fraction
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


def _json_equal(left: Any, right: Any) -> bool:
    """JSON equality: Python's True == 1 must not match enums or uniqueItems."""
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(_json_equal(left[k], right[k]) for k in left)
    if isinstance(left, list) and isinstance(right, list):
        return len(left) == len(right) and all(_json_equal(a, b) for a, b in zip(left, right))
    return left == right


def validate_schema(obj: Any, schema: Any, path: str = "$") -> List[str]:
    """Return local constraint errors; invalid schemas never permit execution."""
    try:
        json.dumps(obj, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return [f'{path}: مقدار JSON معتبر و متناهی نیست']
    try:
        return _validate_schema(obj, schema, path)
    except (TypeError, ValueError, ArithmeticError, re.error):
        return [f'{path}: schema نامعتبر است']


def _validate_schema(obj: Any, schema: Any, path: str) -> List[str]:
    """Local JSON Schema subset for tool arguments, without coercing values.

    Supports types, boolean schemas, objects, homogeneous arrays, bounds and
    allOf/anyOf/oneOf/not. References are explicitly rejected, never fetched.
    This is not a complete JSON Schema implementation (e.g. no format checks).
    """
    if schema is True:
        return []
    if schema is False:
        return [f'{path}: مقدار مجاز نیست']
    if not isinstance(schema, dict):
        return [f'{path}: schema نامعتبر است']
    if '$ref' in schema or '$dynamicRef' in schema:
        return [f'{path}: ارجاع schema پشتیبانی نمی‌شود']
    errs: List[str] = []
    number = isinstance(obj, (int, float)) and not isinstance(obj, bool)
    if number and isinstance(obj, float) and not math.isfinite(obj):
        return [f'{path}: عدد باید متناهی باشد']
    t = schema.get("type")
    if 'type' in schema:
        kinds = {"string": isinstance(obj, str),
                 "integer": number and (isinstance(obj, int) or obj.is_integer()),
                 "number": number, "boolean": isinstance(obj, bool),
                 "object": isinstance(obj, dict), "array": isinstance(obj, list),
                 "null": obj is None}
        types = t if isinstance(t, list) else [t]
        if any(kind not in kinds for kind in types):
            return [f'{path}: نوع schema پشتیبانی نمی‌شود']
        if not any(kinds[kind] for kind in types):
            errs.append(f"{path}: انتظار {t} بود")
            return errs
    for keyword in ('allOf', 'anyOf', 'oneOf'):
        if keyword in schema:
            branches = schema[keyword]
            if not isinstance(branches, list) or not branches:
                errs.append(f'{path}: {keyword} نامعتبر است')
                continue
            matches = sum(not _validate_schema(obj, branch, path) for branch in branches)
            if ((keyword == 'allOf' and matches != len(branches))
                    or (keyword == 'anyOf' and matches == 0)
                    or (keyword == 'oneOf' and matches != 1)):
                errs.append(f'{path}: شرط {keyword} برقرار نیست')
    if 'not' in schema and not _validate_schema(obj, schema['not'], path):
        errs.append(f'{path}: شرط not برقرار نیست')
    if isinstance(obj, dict):
        for req in schema.get("required", []) or []:
            if req not in obj:
                errs.append(f"{path}: فیلد لازم «{req}» نیست")
        props = schema.get("properties", {}) or {}
        for k, v in obj.items():
            if k in props:
                errs += _validate_schema(v, props[k], f"{path}.{k}")
            elif 'additionalProperties' in schema:
                errs += _validate_schema(v, schema['additionalProperties'], f'{path}.{k}')
        for keyword, failed in [('minProperties', len(obj) < schema.get('minProperties', 0)),
                                ('maxProperties', len(obj) > schema.get('maxProperties', math.inf))]:
            if failed:
                errs.append(f'{path}: محدودیت {keyword} برقرار نیست')
    if isinstance(obj, list):
        if 'items' in schema:
            for i, v in enumerate(obj):
                errs += _validate_schema(v, schema['items'], f'{path}[{i}]')
        if len(obj) < schema.get('minItems', 0) or len(obj) > schema.get('maxItems', math.inf):
            errs.append(f'{path}: طول آرایه مجاز نیست')
        if schema.get('uniqueItems') and any(_json_equal(v, other) for i, v in enumerate(obj) for other in obj[:i]):
            errs.append(f'{path}: عناصر آرایه باید یکتا باشند')
    if isinstance(obj, str):
        if len(obj) < schema.get('minLength', 0) or len(obj) > schema.get('maxLength', math.inf):
            errs.append(f'{path}: طول رشته مجاز نیست')
        if 'pattern' in schema:
            try:
                if re.search(schema['pattern'], obj) is None:
                    errs.append(f'{path}: الگوی رشته برقرار نیست')
            except re.error:
                errs.append(f'{path}: الگوی schema نامعتبر است')
    if number:
        for keyword, failed in [('minimum', obj < schema.get('minimum', -math.inf)),
                                ('maximum', obj > schema.get('maximum', math.inf)),
                                ('exclusiveMinimum', obj <= schema.get('exclusiveMinimum', -math.inf)),
                                ('exclusiveMaximum', obj >= schema.get('exclusiveMaximum', math.inf))]:
            if failed:
                errs.append(f'{path}: محدودیت {keyword} برقرار نیست')
        if 'multipleOf' in schema:
            step = Fraction(str(schema['multipleOf']))
            if step <= 0 or Fraction(str(obj)) % step != 0:
                errs.append(f'{path}: مضرب مجاز نیست')
    if 'const' in schema and not _json_equal(obj, schema['const']):
        errs.append(f'{path}: مقدار با const برابر نیست')
    if "enum" in schema and not any(_json_equal(obj, v) for v in schema['enum']):
        errs.append(f"{path}: مقدار باید یکی از {schema['enum']} باشد")
    return errs


def parse_strict(text: str, schema: Optional[Dict[str, Any]] = None) -> Tuple[Any, List[str]]:
    """(آبجکت، خطاهای schema). خطای پارس → raise."""
    obj = parse_loose(text)
    errs = validate_schema(obj, schema) if schema is not None else []
    return obj, errs
