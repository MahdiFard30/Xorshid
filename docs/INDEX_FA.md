# راهنمای پوشه‌های خورشید

دستورها را از ریشهٔ پروژه اجرا کن. دو فایل اجرای اصلی همان‌جا مانده‌اند:

```sh
.venv/bin/python khorshid.py
.venv/bin/python khorshid_live.py
```

دو نسخه از یک پورت رابط و هات‌کی استفاده می‌کنند؛ یکی را ببند و دیگری را اجرا کن. پس از این جابه‌جایی، نسخهٔ باز را یک‌بار دوباره اجرا کن تا کد و مسیرهای تازه بارگذاری شوند.

| مسیر | محتوا |
|---|---|
| `docs/` | همهٔ راهنماها و گزارش‌های Markdown؛ فهرست همین صفحه |
| `docs/guides/` | راهنماهای استفاده و توسعه |
| `docs/trading/` | راهنماهای فعلی معاملهٔ دمو |
| `docs/architecture/` | تحلیل معماری و وضعیت پروژه |
| `docs/archive/` | راهنماهای قدیمی و سابقهٔ ارتقا |
| `ultimate_khorshid/` | کد اصلی، عامل‌ها، حافظه، ابزارها و رابط‌ها |
| `ultimate_khorshid/interface/` | رابط خورشید، پل نمایش و اجرای Gemini Live |
| `ultimate_khorshid/voice/` | صدا، worker اختصاصی، آماده‌سازی و نرمال‌سازی متن |
| `ultimate_khorshid/assets/` | تصویر خورشید و فایل‌های مرجع صدا، با محتوای اصلی |
| `scripts/` | نصب اکسپرت و عیب‌یابی صدا |
| `requirements/` | وابستگی‌های اختصاصی رابط و Live |
| `mt5/` | سورس و فایل کامپایل‌شدهٔ اکسپرت |
| `configs/` | تنظیمات پیش‌فرض |
| `tests/` و `evals/` | تست‌ها و ارزیابی‌ها |
| `local-backups/` | پشتیبان‌های محلی MT5 و README؛ خارج از Git |

`README.md` در ریشه خالی باقی مانده است. فایل‌های مخفی تنظیمات، محیط‌های مجازی و داده‌های حافظه و معاملات در مسیر قبلی خود هستند. هیچ فایل یا داده‌ای در این مرتب‌سازی حذف یا روی GitHub منتشر نشده است.

برای خلوت‌تر بودن نمای VS Code، محیط‌های مجازی و فایل‌های کش پایتون در Explorer پنهان شده‌اند؛ فایل‌هایشان همچنان روی دیسک موجودند. این تنظیم در `.vscode/settings.json` و بخش `files.exclude` است.

## راهنماها

- [اجرای پروژه و دستورهای توسعه](guides/DEVELOPMENT_FA.md)
- [شروع پروژه](guides/START_HERE_FA.md)
- [تحلیل پروژه و وضعیت اصلاحات](architecture/PROJECT_ANALYSIS_FA.md)
- [حافظهٔ خودکار](guides/AUTOMATIC_MEMORY_FA.md)
- [Gemini، Groq و مسیر جایگزین](guides/GROQ_FALLBACK_FA.md)
- [گزارش سرویس پاسخ‌دهنده](guides/PROVIDER_REPORTING_FA.md)
- [حافظه و ارزیابی معاملات فعلی](trading/TRADE_MEMORY_FA.md)
- [بازیابی متاتریدر پس از ری‌استارت](trading/MT5_RESTART_FA.md)
- [خروج پیش از تعطیلی هفتگی](trading/WEEKLY_CLOSE_FA.md)
- [راهنمای قدیمی معاملات دمو](archive/DEMO_TRADER_FA.md)
- [راهنمای قدیمی یادگیری](archive/LEARNING_FA.md)
- ارتقاها: [مرحلهٔ اول](archive/UPGRADE_PHASE1_FA.md)، [دوم](archive/UPGRADE_PHASE2_FA.md)، [سوم](archive/UPGRADE_PHASE3_FA.md)، [چهارم](archive/UPGRADE_PHASE4_FA.md)

## ابزارهای کمکی

برای کارهای روزمره، ابزار توسعهٔ مشترک وجود دارد:

```sh
.venv/bin/python scripts/dev.py run
.venv/bin/python scripts/dev.py live
.venv/bin/python scripts/dev.py doctor
.venv/bin/python scripts/dev.py check
.venv/bin/python scripts/dev.py test
```

ابزارهای تخصصی:

```sh
.venv/bin/python scripts/diagnose_khorshid_voice.py
.venv/bin/python scripts/install_mt5_recovery.py
.venv/bin/python -m ultimate_khorshid.cli.main doctor
.venv/bin/python -m pip install -r requirements/requirements-live.txt
```

دستور نصب اکسپرت بدون `--install` فقط بررسی می‌کند و فایل اکسپرت را تغییر نمی‌دهد. فایل‌های `requirements/` در کنار گزینه‌های نصب `pyproject.toml` نگه‌داری می‌شوند. برای دست‌کاری سورس داخلی Live، فایل `ultimate_khorshid/interface/khorshid_gemini_live_runner.py` را باز کن؛ اجرای معمول همچنان با `khorshid_live.py` است.
