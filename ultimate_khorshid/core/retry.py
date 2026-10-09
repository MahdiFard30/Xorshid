"""Retry + Fallback — تلاش مجدد با backoff و زنجیره جایگزین."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple


def retry(fn: Callable[[], Any], tries: int = 3, backoff: float = 1.0,
          retry_on: Tuple[type, ...] = (Exception,),
          on_retry: Optional[Callable[[int, Exception], None]] = None) -> Any:
    """اجرای fn با تلاش مجدد. آخرین خطا raise می‌شود اگر همه شکست خوردند."""
    last: Optional[Exception] = None
    for attempt in range(1, max(1, tries) + 1):
        try:
            return fn()
        except retry_on as e:
            last = e
            if attempt >= max(1, tries):
                break
            if on_retry:
                try:
                    on_retry(attempt, e)
                except Exception:
                    pass
            time.sleep(backoff * attempt)
    assert last is not None
    raise last


class FallbackChain:
    """زنجیره جایگزین: [(نام، تابع)] — اولی که موفق شد برمی‌گردد."""

    def __init__(self) -> None:
        self._steps: List[Tuple[str, Callable[[], Any]]] = []

    def add(self, name: str, fn: Callable[[], Any]) -> "FallbackChain":
        self._steps.append((name, fn))
        return self

    def run(self) -> Tuple[str, Any, List[str]]:
        """(نام برنده، نتیجه، خطاهای قبلی). اگر همه شکست: آخرین خطا raise."""
        errors: List[str] = []
        last: Optional[Exception] = None
        for name, fn in self._steps:
            try:
                return name, fn(), errors
            except Exception as e:
                last = e
                errors.append(f"{name}: {e}")
        assert last is not None, "زنجیره خالی است"
        raise last


def run_with_fallbacks(primary: Callable[[], Any],
                       fallbacks: Dict[str, Callable[[], Any]]) -> Tuple[str, Any]:
    ch = FallbackChain().add("primary", primary)
    for name, fn in fallbacks.items():
        ch.add(name, fn)
    name, res, _ = ch.run()
    return name, res
