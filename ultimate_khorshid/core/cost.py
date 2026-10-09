"""ردیابی هزینه — جدول قیمت تقریبی مدل‌ها (دلار به‌ازای ۱M توکن) + محاسبه.

قیمت‌ها تقریبی‌اند (به‌روزرسانی دوره‌ای لازم دارد)؛ mock/ollama رایگان‌اند.
"""

from __future__ import annotations

from typing import Dict, Tuple

# (input $/1M, output $/1M) — کلید: زیررشته نام مدل
PRICES: Dict[str, Tuple[float, float]] = {
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-sonnet-4": (3.00, 15.00),
    "qwen": (0.0, 0.0),  # معمولاً لوکال
    "llama": (0.0, 0.0),
}
FREE_ENGINES = {"mock", "ollama"}


def price_for(engine: str, model: str) -> Tuple[float, float]:
    if (engine or "").lower() in FREE_ENGINES:
        return (0.0, 0.0)
    m = (model or "").lower()
    for key, price in PRICES.items():
        if key in m:
            return price
    if (engine or "").lower() in ("gemini", "google"):
        return (0.10, 0.40)
    return (0.50, 1.50)  # پیش‌فرض محافظه‌کار برای ناشناخته‌ها


def calc_usd(engine: str, model: str, tok_in: int, tok_out: int) -> float:
    pin, pout = price_for(engine, model)
    return round(tok_in / 1e6 * pin + tok_out / 1e6 * pout, 6)
