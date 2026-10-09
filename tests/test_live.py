"""تست‌های زنده (نیاز به اینترنت) — فقط با KHORSHID_LIVE=1 اجرا می‌شوند:

    KHORSHID_LIVE=1 python3 -m pytest tests/test_live.py -q
"""

import os

import pytest

pytestmark = pytest.mark.skipif(os.environ.get("KHORSHID_LIVE") != "1",
                                reason="needs KHORSHID_LIVE=1")


def test_live_weather():
    from ultimate_khorshid.tools.weather import WeatherTool
    r = WeatherTool().execute(city="تهران")
    assert r.success and "°C" in r.content, r.content


def test_live_crypto():
    from ultimate_khorshid.runtime import ask
    out = ask("تتر چنده؟")
    assert "تومان" in out or "USDT" in out, out[:200]


def test_live_web_search():
    from ultimate_khorshid.tools.web import WebSearchTool
    r = WebSearchTool().execute(query="قیمت تتر")
    assert r.success and len(r.content) > 100


def test_live_web_fetch_title():
    from ultimate_khorshid.tools.web import WebFetchTool
    r = WebFetchTool().execute(url="https://example.com")
    assert r.success and "Example Domain" in r.content, r.content[:200]


def test_live_telegram_bad_token_fails_clean():
    from ultimate_khorshid.channels.telegram import TelegramBot
    bot = TelegramBot("123456:FAKE-TOKEN-FOR-TEST")
    try:
        bot.me()
        raise AssertionError("باید خطا می‌داد")
    except RuntimeError as e:
        assert "تلگرام" in str(e)


def test_live_ask_weather_routing():
    from ultimate_khorshid.runtime import ask
    assert "°C" in ask("هوای مشهد چطوره؟")
