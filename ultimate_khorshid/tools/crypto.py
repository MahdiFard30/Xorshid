"""ابزار قیمت رمزارز — تتر/بیت‌کوین/... به تومان و دلار (API رایگان، بدون کلید).

- تومان: Nobitex (آزاد، بدون کلید)
- دلار/ارزهای جهانی: CoinGecko (آزاد)
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

UA = {"User-Agent": "Mozilla/5.0 (UltimateKhorshid/1.0)"}

# نماد فارسی → (تیکر، coingecko-id)
COINS: Dict[str, tuple] = {
    "تتر": ("USDT", "tether"), "بیت کوین": ("BTC", "bitcoin"),
    "بیتکوین": ("BTC", "bitcoin"), "بیت‌کوین": ("BTC", "bitcoin"),
    "اتریوم": ("ETH", "ethereum"), "اتر": ("ETH", "ethereum"),
    "دوج": ("DOGE", "dogecoin"), "دوجکوین": ("DOGE", "dogecoin"),
    "سولانا": ("SOL", "solana"), "ریپل": ("XRP", "ripple"),
    "بایننس": ("BNB", "binancecoin"), "ترون": ("TRX", "tron"),
    "کاردانو": ("ADA", "cardano"), "شیبا": ("SHIB", "shiba-inu"),
    "تون": ("TON", "the-open-network"), "ناتکوین": ("NOT", "notcoin"),
    "آوالانچ": ("AVAX", "avalanche-2"), "چینلینک": ("LINK", "chainlink"),
    "پولکادات": ("DOT", "polkadot"), "لایتکوین": ("LTC", "litecoin"),
}
TICKERS = {t: g for t, g in COINS.values()}


def detect_coin(q: str) -> tuple[str, str] | None:
    """پیدا کردن رمزارز از روی متن فارسی/انگلیسی."""
    for fa, (ticker, gecko) in COINS.items():
        if fa in q:
            return ticker, gecko
    import re
    m = re.search(r"\b(USDT|BTC|ETH|DOGE|SOL|XRP|BNB|TRX|ADA|SHIB|TON|NOT|AVAX|LINK|DOT|LTC)\b",
                  q.upper())
    if m and m.group(1) in TICKERS:
        return m.group(1), TICKERS[m.group(1)]
    return None


def fmt(n: float) -> str:
    return f"{n:,.0f}" if n >= 1000 else (f"{n:,.2f}" if n >= 10 else f"{n:.4f}")


def nobitex_price(src: str) -> Dict[str, Any] | None:
    """قیمت به ریال از نوبیتکس (تومان = ریال/۱۰)."""
    url = ("https://apiv2.nobitex.ir/market/stats?" +
           urllib.parse.urlencode({"srcCurrency": src.lower(), "dstCurrency": "rls"}))
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    stats = data.get("stats") or {}
    key = f"{src.lower()}-rls"
    if key in stats and stats[key].get("latest"):
        return {"latest_rls": float(stats[key]["latest"]),
                "day_change": stats[key].get("dayChange", "?")}
    return None


def gecko_price(gecko_id: str, vs: str = "usd") -> float | None:
    url = ("https://api.coingecko.com/api/v3/simple/price?" +
           urllib.parse.urlencode({"ids": gecko_id, "vs_currencies": vs}))
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        data = json.loads(r.read().decode("utf-8"))
    try:
        return float(data[gecko_id][vs])
    except (KeyError, TypeError):
        return None


TGJU_SLUGS = {"USDT": "tether", "BTC": "bitcoin", "ETH": "ethereum", "DOGE": "dogecoin",
              "SOL": "solana", "XRP": "ripple", "BNB": "binance-coin", "TRX": "tron",
              "ADA": "cardano", "LTC": "litecoin", "SHIB": "shiba-inu", "TON": "toncoin",
              "AVAX": "avalanche", "LINK": "chainlink", "XLM": "stellar", "DOT": "polkadot"}

_tgju_cache: dict = {"ts": 0.0, "data": None}


def tgju_all() -> dict:
    """کل جدول TGJU با کش ۶۰ ثانیه‌ای."""
    import time
    if time.time() - _tgju_cache["ts"] < 60 and _tgju_cache["data"]:
        return _tgju_cache["data"]
    url = "https://call5.tgju.org/ajax.json"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=15) as r:
        data = json.loads(r.read().decode("utf-8")).get("current", {})
    _tgju_cache.update(ts=time.time(), data=data)
    return data


def tgju_price(ticker: str, irr: bool = True) -> float | None:
    """قیمت از TGJU (irr=True → ریال، وگرنه دلار)."""
    slug = TGJU_SLUGS.get(ticker)
    if not slug:
        return None
    key = f"crypto-{slug}-irr" if irr else f"crypto-{slug}"
    v = tgju_all().get(key, {}).get("p", "")
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


def tgju_dollar_rls() -> float | None:
    v = tgju_all().get("price_dollar_rl", {}).get("p", "")
    try:
        return float(str(v).replace(",", ""))
    except (ValueError, TypeError):
        return None


@ToolRegistry.register("crypto_price")
class CryptoPriceTool(BaseTool):
    tool_id = "crypto_price"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="crypto_price",
            description="قیمت لحظه‌ای رمزارز (تتر، بیت‌کوین، اتریوم...) به تومان و دلار.",
            parameters={"type": "object", "properties": {
                "symbol": {"type": "string", "description": "تیکر مثل USDT/BTC یا نام فارسی مثل تتر"},
                "currency": {"type": "string", "description": "IRT (تومان) یا USD (دلار) — پیش‌فرض هر دو"}},
                "required": []},
            category="finance", timeout_seconds=70.0)

    def execute(self, **p: Any) -> ToolResult:
        raw = str(p.get("symbol", "تتر") or "تتر").strip()
        cur = str(p.get("currency", "") or "").upper()
        # دلار آزاد؟
        if "دلار" in raw and not detect_coin(raw):
            try:
                rls = tgju_dollar_rls()
                if rls:
                    return ToolResult(tool_name="crypto_price",
                                      content=f"💵 دلار آزاد: {fmt(rls/10)} تومان")
            except Exception:
                pass
            return ToolResult(tool_name="crypto_price",
                              content="❌ قیمت دلار در دسترس نیست.", success=False)
        coin = detect_coin(raw) or detect_coin(raw.upper())
        if coin is None:
            return ToolResult(tool_name="crypto_price", content=f"رمزارز پشتیبانی نمی‌شود: {raw}", success=False)
        ticker, gecko = coin
        fa_name = next((k for k, v in COINS.items() if v[0] == ticker), ticker)
        lines = [f"💰 {fa_name} ({ticker}):"]
        ok = False
        if cur in ("", "IRT", "TOMAN", "تومان"):
            toman = None
            try:
                nb = nobitex_price(ticker)
                if nb:
                    toman = nb["latest_rls"] / 10
            except Exception:
                pass
            if toman is None:  # fallback: TGJU
                try:
                    rls = tgju_price(ticker, irr=True)
                    if rls:
                        toman = rls / 10
                except Exception:
                    pass
            if toman:
                lines.append(f"  • تومان: {fmt(toman)} تومان")
                ok = True
        if cur in ("", "USD", "دلار"):
            usd = None
            try:
                usd = gecko_price(gecko, "usd")
            except Exception:
                pass
            if usd is None:  # fallback: TGJU
                try:
                    usd = tgju_price(ticker, irr=False)
                except Exception:
                    pass
            if usd:
                lines.append(f"  • دلار: ${fmt(usd)}")
                ok = True
        if not ok:
            return ToolResult(tool_name="crypto_price",
                              content="❌ نتوانستم قیمت را بگیرم (اینترنت/سرویس).", success=False)
        return ToolResult(tool_name="crypto_price", content="\n".join(lines))
