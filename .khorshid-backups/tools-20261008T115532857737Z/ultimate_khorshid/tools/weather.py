"""ابزار هواشناسی — دمای فعلی + وضعیت هوا برای شهرهای ایران و جهان.

منبع: Open-Meteo (رایگان، بدون API key).
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any, Dict

from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

UA = {"User-Agent": "Mozilla/5.0 (UltimateKhorshid/2.0)"}

# نام فارسی → نام انگلیسی برای ژئوکدینگ دقیق‌تر
CITIES_FA: Dict[str, str] = {
    "تهران": "Tehran", "مشهد": "Mashhad", "اصفهان": "Isfahan",
    "شیراز": "Shiraz", "تبریز": "Tabriz", "کرج": "Karaj",
    "قم": "Qom", "اهواز": "Ahvaz", "کرمان": "Kerman",
    "یزد": "Yazd", "رشت": "Rasht", "زاهدان": "Zahedan",
    "همدان": "Hamedan", "ارومیه": "Urmia", "گرگان": "Gorgan",
    "ساری": "Sari", "بندرعباس": "Bandar Abbas", "بوشهر": "Bushehr",
    "خرم‌آباد": "Khorramabad", "خرم آباد": "Khorramabad",
    "سنندج": "Sanandaj", "کرمانشاه": "Kermanshah", "اراک": "Arak",
    "قزوین": "Qazvin", "زنجان": "Zanjan", "سمنان": "Semnan",
    "بیرجند": "Birjand", "شهرکرد": "Shahrekord", "یاسوج": "Yasuj",
    "بجنورد": "Bojnord", "ایلام": "Ilam", "اردبیل": "Ardabil",
    "استانبول": "Istanbul", "دبی": "Dubai", "دوحه": "Doha",
}

# کد هوای WMO → فارسی
WMO_FA: Dict[int, str] = {
    0: "آسمان صاف ☀️", 1: "کم‌وبیش صاف 🌤️", 2: "نیمه‌ابری ⛅", 3: "ابری ☁️",
    45: "مه‌آلود 🌫️", 48: "مه یخ‌زده 🌫️",
    51: "نم‌نم باران 🌦️", 53: "نم‌نم باران 🌦️", 55: "نم‌نم شدید 🌧️",
    56: "نم‌نم یخ‌زده 🌧️", 57: "نم‌نم یخ‌زده 🌧️",
    61: "باران خفیف 🌧️", 63: "باران 🌧️", 65: "باران شدید ⛈️",
    66: "باران یخ‌زده 🌧️", 67: "باران یخ‌زده 🌧️",
    71: "برف خفیف 🌨️", 73: "برف 🌨️", 75: "برف سنگین ❄️", 77: "دانه برف 🌨️",
    80: "نمای باران 🌦️", 81: "نمای باران 🌦️", 82: "رگبار شدید ⛈️",
    85: "برف پراکنده 🌨️", 86: "برف پراکنده 🌨️",
    95: "رعدوبرق ⛈️", 96: "رعدوبرق با تگرگ ⛈️", 99: "رعدوبرق با تگرگ ⛈️",
}


def describe_wmo(code: int) -> str:
    return WMO_FA.get(int(code), "نامشخص")


def _get_json(url: str, timeout: float = 15.0) -> Dict[str, Any]:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA),
                                timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def geocode(city: str) -> tuple[float, float, str] | None:
    """شهر → (lat, lon, نام رسمی)."""
    q = CITIES_FA.get(city.strip(), city.strip())
    url = ("https://geocoding-api.open-meteo.com/v1/search?" +
           urllib.parse.urlencode({"name": q, "count": 1, "language": "fa",
                                   "format": "json"}))
    data = _get_json(url)
    res = (data.get("results") or [None])[0]
    if not res:
        return None
    name = res.get("name") or q
    country = res.get("country") or ""
    label = f"{name} ({country})" if country else name
    return float(res["latitude"]), float(res["longitude"]), label


def current_weather(lat: float, lon: float) -> Dict[str, Any]:
    url = ("https://api.open-meteo.com/v1/forecast?" +
           urllib.parse.urlencode({"latitude": lat, "longitude": lon,
                                   "current": "temperature_2m,relative_humidity_2m,"
                                              "weather_code,wind_speed_10m",
                                   "timezone": "auto"}))
    return _get_json(url)


@ToolRegistry.register("weather")
class WeatherTool(BaseTool):
    tool_id = "weather"

    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="weather",
            description="هوای فعلی یک شهر (دما، وضعیت، رطوبت، باد). مثال شهر: تهران، مشهد، Istanbul",
            parameters={"type": "object", "properties": {
                "city": {"type": "string", "description": "نام شهر (فارسی یا انگلیسی)"}},
                        "required": []},
            category="web")

    def execute(self, **p):
        city = str(p.get("city", "") or "").strip() or "تهران"
        try:
            geo = geocode(city)
        except Exception as e:
            return ToolResult(tool_name="weather",
                              content=f"❌ خطا در پیدا کردن شهر «{city}»: {e}",
                              success=False)
        if not geo:
            return ToolResult(tool_name="weather",
                              content=f"❌ شهر «{city}» پیدا نشد. نام دیگری امتحان کن.",
                              success=False)
        lat, lon, label = geo
        try:
            data = current_weather(lat, lon)
        except Exception as e:
            return ToolResult(tool_name="weather",
                              content=f"❌ خطا در دریافت هوا: {e}", success=False)
        cur = data.get("current") or {}
        t = cur.get("temperature_2m", "?")
        h = cur.get("relative_humidity_2m", "?")
        w = cur.get("wind_speed_10m", "?")
        desc = describe_wmo(cur.get("weather_code", -1))
        return ToolResult(
            tool_name="weather",
            content=(f"🌤️ هوای {label}:\n"
                     f"  • وضعیت: {desc}\n"
                     f"  • دما: {t}°C\n"
                     f"  • رطوبت: {h}٪\n"
                     f"  • باد: {w} km/h"))
