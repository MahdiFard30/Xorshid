"""دموی سریع — اجرای آفلاین همه قابلیت‌های اصلی."""

from ultimate_khorshid.runtime import KhorshidRuntime, list_agents, list_tools
from ultimate_khorshid.core.config import KhorshidConfig

rt = KhorshidRuntime(KhorshidConfig())
print(f"ایجنت‌ها ({len(list_agents())}): {list_agents()}")
print(f"ابزارها ({len(list_tools())}): {sorted(list_tools())}\n")

for q in [
    "سلام!",
    "حساب کن: 2**10 + sqrt(144)",
    "ساعت چند است؟",
    "مشخصات سیستم را بگو",
    "به خاطر بسپار: رنگ موردعلاقه من آبی است",
    "یادت هست رنگ موردعلاقه من چیست؟",
    "یک تودو اضافه کن: خرید شیر",
    "لیست فایل‌های پوشه . را نشان بده",
]:
    print(f"\n{'='*60}\n❓ {q}\n{'='*60}")
    print(rt.ask(q).content[:1200])
