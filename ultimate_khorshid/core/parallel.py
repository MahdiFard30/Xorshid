"""اجرای موازی ابزارها با ThreadPool (برای I/O-bound مثل fetch چند URL)."""

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, Dict, Tuple


def run_parallel(tasks: Dict[str, Callable[[], Any]],
                 max_workers: int = 5,
                 timeout: float | None = 120.0) -> Dict[str, Tuple[bool, Any]]:
    """{نام: تابع} -> {نام: (موفق؟, نتیجه/خطا)}. ترتیب ورودی حفظ نمی‌شود."""
    out: Dict[str, Tuple[bool, Any]] = {}
    if not tasks:
        return out
    with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(max_workers, len(tasks))),
            thread_name_prefix="khorshid-par") as pool:
        futs = {pool.submit(_wrap, fn): name for name, fn in tasks.items()}
        try:
            done, _ = concurrent.futures.wait(futs, timeout=timeout)
        except Exception:
            done = set()
        for fut, name in futs.items():
            if fut in done:
                try:
                    out[name] = (True, fut.result())
                except Exception as e:
                    out[name] = (False, f"{e}")
            else:
                out[name] = (False, f"timeout بعد از {timeout} ثانیه")
                fut.cancel()
    return out


def _wrap(fn: Callable[[], Any]) -> Any:
    return fn()
