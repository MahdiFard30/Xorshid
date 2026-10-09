<div align="center">

# 🤖 ULTIMATE KHORSHID — خورشید نهایی (نسخه ۲.۱)

**قدرتمندترین ایجنت کامپیوتری پایتونی — فارسی‌زبان، آفلاین‌دوست، همه‌کاره**

*الهام‌گرفته از معماری [OpenJarvis استنفورد](https://github.com/open-jarvis/OpenJarvis) — بازطراحی‌شده برای «کامپیوتر ایجنتی که واقعاً هر کاری انجام می‌دهد»: فایل، شل، وب، مرورگر واقعی، دسکتاپ، صدا، تلگرام و...*

![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)
![Version](https://img.shields.io/badge/version-2.0-purple)
![Deps](https://img.shields.io/badge/core-zero%20dependency%20(stdlib)-green)
![Agents](https://img.shields.io/badge/agents-13-orange)
![Tools](https://img.shields.io/badge/tools-51-red)
![Tests](https://img.shields.io/badge/tests-52%20passing-brightgreen)
![License](https://img.shields.io/badge/license-Apache%202.0-green)

[نصب موبه‌مو](#-نصب-قدمبهقدم-موبه‌مو) • [شروع سریع](#-شروع-سریع) • [داشبورد](#-داشبورد-وب-فارسی) • [پوش‌تو‌تاک](#-پوش‌تو‌تاک-احضار-سریع) • [تلگرام](#-ربات-تلگرام-کنترل-از-موبایل) • [عیب‌یابی](#-عیب‌یابی)

</div>

---

## ✨ چرا خورشید نهایی؟

| ویژگی | توضیح |
|---|---|
| 🖥️ **کامپیوتر ایجنت واقعی** | فایل، شل، پایتون، گیت، وب، **مرورگر واقعی، موس/کیبورد، اسکرین‌شات، بینایی** — همه را خودش انجام می‌دهد |
| 🌐 **داشبورد وب فارسی** | ۱۰ پنل: چت، صدا، مرورگر، آزمون، تاریخچه، اسکرین‌شات زنده، تودو، حافظه، تنظیمات (`khorshid ui`) |
| 🎙️ **پوش‌تو‌تاک سراسری** | مثل بی‌سیم: Ctrl را نگه دار، حرف بزن، ول کن تا اجرا شود! |
| 📱 **ربات تلگرام** | کنترل کامل خورشید از موبایل، فقط با stdlib (بدون وابستگی) |
| 📝 **حل خودکار آزمون** | «سؤال‌های سایت را جواب بده» → می‌خواند، جواب می‌دهد، گزینه صحیح را می‌زند |
| 🇮🇷 **فارسی اول** | پرسونای فارسی، تاریخ شمسی، موتور آفلاین فارسی‌فهم، قیمت تتر/دلار به تومان |
| 📦 **هسته صفر وابستگی** | موتورها، سرور و ابزارهای اصلی فقط با کتابخانه استاندارد پایتون |
| 🧠 **۱۳ ایجنت** | ۹ ایجنت یکتا + ۴ نام مستعار؛ از گپ ساده تا خودمختار هدف‌محور |
| 🔧 **۵۱ ابزار** | رجیستری دکوراتوری مثل OpenJarvis — ساخت ابزار جدید در ۲۰ خط |
| 🌤️ **هواشناسی + اعلان** | هوای شهرها (رایگان، بدون کلید) و نوتیفیکیشن دسکتاپ |
| 💰 **قیمت زنده** | تتر/بیت‌کوین/دلار به تومان و دلار (TGJU + CoinGecko + نوبیتکس) |
| 💾 **حافظه دائمی** | SQLite + FTS5 + ایندکس اسناد شخصی |
| 🎓 **۹ مهارت داخلی** | استاندارد `agentskills.io` (اپراتور کامپیوتر/مرورگر/تلگرام، حل آزمون...) |
| ⏰ **زمان‌بند** | تسک‌های دوره‌ای (گزارش صبحگاهی، یادآور...) |
| 🌐 **سرور سازگار با OpenAI** | `/v1/chat/completions` + ۲۰ مسیر API، بدون نیاز به FastAPI (ولی FastAPI اختیاری هم هست) |
| 🧠 **۴ موتور استنتاج** | آفلاین (mock) + اولّاما + Gemini + هر API سازگار با OpenAI |
| 🛡️ **امنیت** | تأیید دستورات خطرناک، بلاک‌لیست، اسکن secret، audit log |
| 🧙 **ویزارد نصب** | `khorshid setup` — راه‌اندازی قدم‌به‌قدم در ۱ دقیقه |

---

## 🛠️ نصب قدم‌به‌قدم (موبه‌مو)

### قدم ۰ — پیش‌نیاز: پایتون 3.10+

| سیستم | دستور |
|---|---|
| 🐧 اوبونتو/دبیان | `sudo apt update && sudo apt install python3 python3-pip` |
| 🎩 فدورا | `sudo dnf install python3 python3-pip` |
| 🪟 ویندوز | از [python.org](https://www.python.org/downloads/) نصب کن و حتماً تیک **Add python to PATH** را بزن |
| 🍎 مک | `brew install python3` |

بررسی:
```bash
python3 --version   # باید 3.10 یا بالاتر باشد (ویندوز: py --version)
```

### قدم ۱ — گرفتن سورس

```bash
# اگر گیت داری:
git clone <آدرس-ریپو> ultimate-khorshid && cd ultimate-khorshid
# اگر فایل زیپ داری: استخراجش کن و وارد پوشه‌اش شو
cd ultimate-khorshid
```

### قدم ۲ — نصب (دو راه)

**راه آسان — اسکریپت نصب:**
```bash
./install.sh --all     # لینوکس/مک: نصب کامل
.\install.ps1 -All     # ویندوز (PowerShell): نصب کامل
```

**راه دستی:**
```bash
pip install -e .                 # هسته (صفر وابستگی) — ویندوز: py -m pip install -e .
pip install -e ".[all]"          # کامل: سرور+مرورگر+دسکتاپ+صدا+هات‌کی
playwright install chromium      # مرورگر واقعی (فقط اگر browser/all نصب کردی)
```

| اکسترا | چه می‌دهد | دستور |
|---|---|---|
| `server` | FastAPI اختیاری | `pip install -e ".[server]"` |
| `browser` | مرورگر واقعی (Playwright) | `pip install -e ".[browser]"` + `playwright install chromium` |
| `desktop` | موس/کیبورد/اسکرین‌شات | `pip install -e ".[desktop]"` |
| `voice` | ضبط/پخش بهتر صدا | `pip install -e ".[voice]"` |
| `hotkey` | پوش‌تو‌تاک سراسری | `pip install -e ".[hotkey]"` |
| `test` | اجرای تست‌ها | `pip install -e ".[test]"` |
| `all` | همه موارد بالا | `pip install -e ".[all]"` |

> 💡 صدا در لینوکس (اختیاری ولی پیشنهادی): `sudo apt install alsa-utils espeak-ng`

### قدم ۳ — ویزارد نصب 🧙 (پیشنهاد می‌شود)

```bash
khorshid setup
```

ویزارد قدم‌به‌قدم می‌پرسد: **موتور** (آفلاین/اولّاما/Gemini/OpenAI) → **کلید API** (اگر لازم بود) → **اکستراها** → **کلید پوش‌تو‌تاک** → ذخیره کانفیگ در `~/.ultimate-jarvis/config.toml`.

نسخه غیرتعاملی (برای اسکریپت):
```bash
khorshid setup --engine gemini --key "AIza..." --extras none --hotkey ctrl --yes
```

### قدم ۴ — بررسی سلامت 🩺

```bash
khorshid doctor
```

خروجی نمونه سالم:
```
🩺 Ultimate Khorshid Doctor
  پایتون: 3.13 | سیستم: Linux ...
  نسخه: 2.0.0
  ایجنت‌ها: 13 | ابزارها: 51 | مهارت‌ها: 9
  ollama: ✅ ...
  gemini_api_key: ✅ تنظیم شده
  ...
```

### قدم ۵ — سلام قربان! 👋

```bash
khorshid ask "تتر چنده؟"     # قیمت زنده
khorshid ui                  # داشبورد فارسی → http://127.0.0.1:8899
```

> 🪟 **نکته ویندوز:** به‌جای `python3` از `py` استفاده کن. اگر دستور `khorshid` شناخته نشد، ترمینال را ببند و دوباره باز کن (PATH به‌روز شود).

---

## ⚡ شروع سریع

```bash
# گفت‌وگوی تعاملی (پیش‌فرض: ایجنت کامپیوتر + موتور آفلاین)
khorshid chat

# یک سؤال تکی
khorshid ask "ساعت چند است؟"
khorshid ask "حساب کن: 2**16 + sqrt(81)"
khorshid ask "هوای تهران چطوره؟"              # 🌤️ جدید!
khorshid ask "لیست فایل‌های پوشه . را نشان بده"
khorshid ask "بنویس در /tmp/note.txt: سلام خورشید"

# ایجنت خاص
khorshid ask "تحقیق کن درباره آخرین مدل‌های زبانی" --agent researcher
khorshid ask "یک اسکریپت بنویس که اعداد اول تا ۱۰۰ را چاپ کند و اجرایش کن" --agent codeact

# ابزار مستقیم
khorshid tools
khorshid tools --call calculator --params '{"expression": "7*8"}'
khorshid tools --call weather --params '{"city": "مشهد"}'

# حافظه
khorshid memory --add "رنگ موردعلاقه من آبی است"
khorshid memory --search "رنگ"
khorshid memory --ingest ~/Documents   # ایندکس اسناد در حافظه

# 🖥️ داشبورد وب فارسی
khorshid ui      # → http://127.0.0.1:8899

# سرور API (سازگار با OpenAI)
khorshid serve

# مثال‌های «هر کاری»:
khorshid ask "تتر چنده؟"                          # قیمت زنده تومان+دلار
khorshid ask "برو توی گوگل سرچ کن تتر چنده"       # مرورگر واقعی باز می‌کند و سرچ می‌کند!
khorshid ask "از صفحه اسکرین‌شات بگیر"            # دیدن صفحه
khorshid ask "بگو سلام قربان"                     # حرف زدن با صدا

# 🎙️ پوش‌تو‌تاک: Ctrl را نگه دار → حرف بزن → ول کن → اجرا می‌شود!
khorshid hotkey --test                 # یک تست سریع
khorshid hotkey --set "ctrl+shift+j"   # تغییر ترکیب (اختیاری)
khorshid hotkey --daemon               # روشن ماندن و گوش دادن
khorshid hotkey --status               # وضعیت دیمون
khorshid hotkey --stop                 # توقف دیمون

# 📝 حل خودکار آزمون یک سایت (نیاز به Playwright + مغز واقعی)
khorshid quiz --url "https://example.com/quiz"
khorshid ask "سوال‌های این صفحه را جواب بده" --agent quiz

# 📱 ربات تلگرام (کنترل از موبایل!)
khorshid telegram --token 123456:AAE... --allow 123456789

# زمان‌بند
khorshid schedule --add "خلاصه وضعیت گیت پروژه را بگو" --every 3600 --name daily-git
khorshid schedule --run
```

### در کد پایتون

```python
from ultimate_khorshid.runtime import ask, KhorshidRuntime

# یک خطی
print(ask("ساعت چند است؟"))

# کامل
rt = KhorshidRuntime()
result = rt.ask("فایل‌های پایتون این پوشه را پیدا کن و تعداد خطوط هرکدام را بگو")
print(result.content)
```

---

## 🖥️ داشبورد وب فارسی

```bash
khorshid ui   # → http://127.0.0.1:8899
```

| پنل | کار |
|---|---|
| 💬 چت | گفت‌وگو با انتخاب ایجنت + چت صوتی مرورگر + دکمه کپی |
| ⚙️ تنظیمات | تغییر هات‌کی، اکشن، موتور، مدل و صدا (ذخیره خودکار) |
| 🌐 مرورگر واقعی | باز کردن آدرس، سرچ گوگل، کلیک، تایپ، اسنپ‌شات، اسکرین‌شات |
| 📝 حل آزمون سایت | آدرس بده → سؤال‌ها خوانده و گزینه صحیح زده می‌شود |
| 🕘 تاریخچه گفت‌وگو | کلیک = اجرای مجدد؛ خروجی JSON؛ پاک‌سازی |
| 📸 صفحه کامپیوتر | اسکرین‌شات زنده + **تحلیل صفحه با بینایی** 🔍 |
| 📋 تودو | لیست کارها |
| 🧠 حافظه | جست‌وجو و افزودن خاطره |
| 🖥️ سیستم | مشخصات سیستم |
| 🔧 ابزارها | لیست ۵۱ ابزار با دسته‌بندی |

API کامل هم دارد (۲۰ مسیر): `/api/chat` `/api/quiz` `/api/browser` `/api/vision` `/api/settings` `/api/history` ... + سازگاری OpenAI (`/v1/chat/completions`، `/v1/models`).

---

## 🎙️ پوش‌تو‌تاک (احضار سریع)

مثل بی‌سیم، از **هرجای سیستم**:

```
Ctrl را نگه دار ──→ 🎤 «حرف بزن!» ──→ ول کن ──→ ⚙️ اجرا + 🔊 جواب
```

**چرا با Ctrl+C تداخل نمی‌کند؟** سه لایه محافظ: ⏱️ آستانه ۰.۲۵ ثانیه (ضربه سریع ضبط را روشن نمی‌کند) + 🚫 لغو هوشمند اگر کلید دیگری هم زده شود + ⏲️ سقف ۳۰ ثانیه‌ای ضبط.

```bash
pip install -e ".[hotkey]"   # + نیاز به arecord یا ffmpeg و میکروفون
khorshid hotkey --daemon      # روشن ماندن (لاگ در ~/.ultimate-jarvis/hotkey.log)
```

ترکیب دلخواه (`ctrl+shift+j`، `alt`...) از داشبورد یا `khorshid hotkey --set` — تک‌کلید = نگه‌داشتن، ترکیب = نگه‌داشتن همه.

---

## 📱 ربات تلگرام (کنترل از موبایل)

```bash
# ۱. به @BotFather پیام بده → /newbot → توکن بگیر
# ۲. اجرا:
khorshid telegram --token 123456:AAE... --allow 123456789,@myusername
# یا با متغیر محیطی:
export KHORSHID_TELEGRAM_TOKEN=123456:AAE...
khorshid telegram
```

داخل چت: هر متنی = `khorshid ask` + دستورات `/help` `/agents` `/tools` `/doctor`.
امنیت: حتماً `--allow` بگذار (آیدی عددی‌ات از ربات @userinfobot). بدون وابستگی اضافه کار می‌کند (فقط stdlib).

---

## 🤖 ایجنت‌ها (۱۴ نام = ۱۰ یکتا + ۴ مستعار)

| ایجنت | کاربرد |
|---|---|
| `computer` ⭐ | **پیش‌فرض** — کامپیوتر ایجنت همه‌کاره (فایل/شل/وب/مرورگر/حافظه/todo) |
| `simple` | گپ تک‌نوبتی بدون ابزار (سریع و ارزان) |
| `react` (+`native_react`) | حلقه Thought/Action/Observation متنی (کار با هر مدلی حتی ضعیف) |
| `orchestrator` | حلقه function-calling چندنوبتی (برای مدل‌های tool-aware) |
| `codeact` (+`native_openhands`) | تولید و اجرای کد پایتون |
| `planner` | شکستن کار به گام‌ها + اجرای گام‌به‌گام |
| `researcher` (+`deep_research`) | تحقیق عمیق چندمرحله‌ای با استناد |
| `autonomous` (+`operative`) | خودمختار هدف‌محور با داور اتمام |
| `quiz` 📝 | حل خودکار آزمون سایت: خواندن سؤال‌ها + انتخاب گزینه صحیح |
| `supervisor` 🧠 | سوپروایزر چندایجنتی: شکستن تسک، سپردن هر گام به بهترین ساب‌ایجنت، جمع‌بندی |

روتر هوشمند (`intelligence/router.py`) به‌صورت خودکار بهترین ایجنت را انتخاب می‌کند.

---

## 🔧 ابزارها (۵۶ عدد)

| دسته | ابزارها |
|---|---|
| استدلال | `think` `calculator` |
| فایل | `file_read` `file_write` `file_edit` `file_list` `file_search` `file_copy` `file_move` `file_delete` |
| اجرا | `shell_exec` `python_exec` |
| وب سریع | `web_search` `web_fetch` (+استخراج تایتل) `http_request` `web_fetch_many` (موازی) |
| 🌐 مرورگر واقعی | `browser_open` `browser_snapshot` `browser_click` `browser_type` `browser_press` `browser_text` `browser_screenshot` `browser_google_search` `browser_forms` `browser_check` `browser_select_option` `browser_close` `browser_a11y` `browser_wait` |
| 🖥️ دسکتاپ | `screenshot` `mouse_move` `mouse_click` `mouse_scroll` `key_press` `key_hotkey` `type_text` `open_url` `open_app` `clipboard` `display_info` |
| 👁️ بینایی | `vision_ask` (فهمیدن صفحه با Gemini) `vision_locate` `vision_click` (کلیک روی دکمه با شبکه SoM) |
| 💰 مالی | `crypto_price` (تتر/بیت‌کوین/دلار...) |
| 🌤️ هوا (جدید) | `weather` (دما/وضعیت/رطوبت/باد هر شهر — رایگان، بدون کلید) |
| 🔔 اعلان (جدید) | `notify` (نوتیفیکیشن دسکتاپ — یادآور و پایان تسک) |
| 🎙️ صوت | `speak` `listen` |
| سیستم | `datetime_now` (شمسی+میلادی) `sysinfo` `process_list` `git` |
| بهره‌وری | `todo` `memory_store` `memory_search` |

### ساخت ابزار جدید (۲۰ خط!)

```python
from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec

@ToolRegistry.register("my_tool")
class MyTool(BaseTool):
    @property
    def spec(self) -> ToolSpec:
        return ToolSpec(name="my_tool", description="...",
            parameters={"type": "object", "properties": {"x": {"type": "string"}}},
            category="demo")
    def execute(self, **p):
        return ToolResult(tool_name="my_tool", content=f"got {p.get('x')}")
```

فقط کافی است ماژول را به `TOOL_MODULES` در `runtime.py` اضافه کنی — همین!

---

## 🧠 موتورها (۴ عدد)

| موتور | نیاز | توضیح |
|---|---|---|
| همه موتورها (۲.۱) | — | توکن‌استریمینگ واقعی (SSE) + tool-calling ساخت‌یافته + کلید از Vault |
| `mock` (پیش‌فرض) | هیچ | مغز قاعده‌محور فارسی — آفلاین کامل، مناسب تست و کارهای دترمینیستیک |
| `ollama` | Ollama | مدل‌های لوکال مثل `qwen2.5:7b` (عالی برای فارسی) — حریم خصوصی کامل |
| `gemini` | API key رایگان | مغز ابری گوگل + بینایی + TTS/STT فارسی |
| `openai_compat` | API key | هر API سازگار با OpenAI: خود OpenAI، DeepSeek، OpenRouter، vLLM، LM Studio... |

```bash
# اتصال به Ollama (بعد از ollama pull qwen2.5:7b)
export KHORSHID_ENGINE=ollama KHORSHID_MODEL=ollama/qwen2.5:7b
khorshid chat

# اتصال به Gemini (کلید رایگان از aistudio.google.com)
export GEMINI_API_KEY=AIza... KHORSHID_ENGINE=gemini
khorshid chat

# اتصال به OpenAI / DeepSeek
export OPENAI_API_KEY=sk-... KHORSHID_ENGINE=openai_compat KHORSHID_MODEL=openai/gpt-4o-mini
khorshid chat
```

---

## ⚙️ کانفیگ

`khorshid setup` یا `khorshid init --preset gemini` کانفیگ را در `~/.ultimate-jarvis/config.toml` می‌سازد:

```toml
[intelligence]
default_model = "gemini/gemini-2.0-flash"
[agent]
default_agent = "computer"
max_turns = 12
[engine.gemini]
model = "gemini-2.0-flash"
voice = "Kore"
```

پریست‌ها: `default` (آفلاین) • `computer-agent` (Ollama) • `chat-simple` (سبک) • `gemini` (ابری+صدا)

### متغیرهای محیطی

| متغیر | اثر |
|---|---|
| `KHORSHID_ENGINE` / `KHORSHID_MODEL` | موتور و مدل پیش‌فرض (`mock` / `ollama` / `gemini` / `openai_compat`) |
| `KHORSHID_CONFIG` | مسیر فایل کانفیگ دلخواه |
| `KHORSHID_VOICE` | صدای TTS (`Kore`، `Charon`، `Fenrir`...) |
| `GEMINI_API_KEY` / `GOOGLE_API_KEY` | کلید Gemini (مغز + بینایی + صدا) |
| `OPENAI_API_KEY` | کلید OpenAI/سازگارها |
| `KHORSHID_TELEGRAM_TOKEN` | توکن ربات تلگرام |

تنظیمات داشبورد (`~/.ultimate-jarvis/settings.json`) روی همه این‌ها سوار می‌شود: `hotkey`، `hotkey_action`، `engine`، `model`، `voice`.

---

## 🚀 جدید در ۲.۱ — زیرساخت مقیاس‌پذیری

۱۸ شکاف معماری که جلوی رشد به بنچمارک‌های واقعی (OSWorld/GAIA/WebArena) و محصول را می‌گرفت، بسته شد:

| حوزه | چه اضافه شد |
|---|---|
| 🔍 ردیابی | SQLite trace/span/usage برای هر `ask` — `khorshid traces` و `khorshid traces --show <id>` |
| 💰 هزینه | جدول $/1M + `khorshid costs` — جمع و به‌تفکیک مدل |
| 🧠 حافظه متنی | بودجه توکن هر ایجنت + برش sliding-window + خلاصه‌ساز خودکار تاریخچه |
| 🔁 پایداری | retry با backoff، زنجیره fallback (موتور/ابزار)، لغو/توقف همکاری (`Ctrl+C` امن) |
| 📦 JSON مقاوم | تعمیر fences/کاما/ناقصی + اعتبارسنجی schema برای tool-callها |
| 💾 چک‌پوینت | ذخیره/ادامه اجراهای چندمرحله‌ای — `khorshid checkpoints` و `ask --resume` |
| 📋 بلک‌برد | حافظه مشترک ساب‌ایجنت‌ها در سوپروایزر |
| 🔐 Vault | زنجیره کلید: env → keyring سیستم‌عامل → کانفیگ — `khorshid vault` |
| 🐳 سندباکس | اجرای شل/پایتون در docker ← firejail ← محیط محدود + لیست سیاه `rm -rf` |
| 🛡️ ضدتزریق | اسکن فارسی+انگلیسی prompt-injection روی ورودی وب + قاب‌بندی spotlight |
| 🧠 حافظه معنایی | TF-IDF هیبرید (بدون مدل!) که بازنویسی سؤال را هم می‌فهمد |
| ⚡ استریم | `khorshid ask --stream` — دیدن توکن‌ها زنده، در همه موتورها |
| 🧠 سوپروایزر | ایجنت ۱۴م: split → route → delegate → merge |
| 🎙️ صوت آفلاین | STT محلی faster-whisper ← Gemini ← Google + کلمه بیدارباش — `khorshid wake` |
| 🖱️ کلیک بینایی | SoM: شبکه A1..H6 روی اسکرین‌شات → مختصات دکمه → کلیک |
| 🌐 ابزارهای وب | `web_fetch_many` (موازی) + `browser_a11y` (درخت دسترس‌پذیری) + `browser_wait` |
| 🧪 ارزیابی | سوئیت رگرسیون `evals/` + دستور `khorshid eval` (۱۰ تسک آفلاین که همیشه باید پاس شوند) |

```bash
khorshid ask "تحقیق کن ..." --stream     # استریم زنده
khorshid traces --limit 5                # تاریخچه اجراها
khorshid costs                           # هزینه مصرف‌شده
khorshid eval                            # سوئیت رگرسیون آفلاین
khorshid wake --once                     # تست کلمه بیدارباش
```

---

## 🧪 تست (۹۳ تست)

```bash
python3 -m pytest tests/ evals/ -q   # ۸۷ تست (۷۷ واحد + ۱۰ رگرسیون آفلاین)
KHORSHID_LIVE=1 python3 -m pytest tests/test_live.py -q   # ۶ تست زنده (اینترنت)
python3 -m pyflakes ultimate_khorshid tests evals  # باید صفر باشد ✅
python3 examples/demo.py              # دموی تعاملی
```

---

## 🛡️ امنیت

- ابزارهای خطرناک (`shell_exec`، `python_exec`، `file_delete`) در حالت تعاملی **تأیید می‌خواهند**.
- دستورات مخرب (`rm -rf /`، `mkfs`، fork-bomb...) **همیشه مسدود** هستند.
- فایل‌های حساس (`.env`، کلیدها، `credentials`) **قابل خواندن نیستند**.
- ربات تلگرام با `--allow` فقط به خودت جواب می‌دهد.
- همه رویدادها در `~/.ultimate-jarvis/audit.db` ثبت می‌شوند.
- (۲.۱) اجرای کد در **سندباکس** (docker ← firejail ← محیط محدود)، اسکن **تزریق فارسی+انگلیسی** روی محتوای وب، و کلیدها در **Vault** (keyring سیستم‌عامل).

---

## 🔧 عیب‌یابی

| مشکل | راه‌حل |
|---|---|
| `khorshid: command not found` | ترمینال را ببند/باز کن؛ یا `python3 -m ultimate_khorshid.cli.main` |
| `playwright` خطای مرورگر | `playwright install chromium` (+ در لینوکس: `playwright install-deps`) |
| هات‌کی در لینوکس کار نمی‌کند | Wayland محدودیت دارد؛ با X11 وارد شو یا `sudo khorshid hotkey --daemon` |
| هات‌کی در مک کار نمی‌کند | System Settings → Privacy → Accessibility → ترمینال را مجاز کن |
| ضبط صدا نشد | لینوکس: `sudo apt install alsa-utils ffmpeg`؛ میکروفون پیش‌فرض را چک کن |
| `ollama: Connection refused` | اول `ollama serve` و `ollama pull qwen2.5:7b` |
| خطای 400 گوگل | کلید Gemini اشتباه/منقضی است؛ از aistudio.google.com کلید نو بگیر |
| ربات تلگرام وصل نمی‌شود | توکن را چک کن؛ در ایران ممکن است به پروکسی/VPN نیاز باشد |
| پورت 8899 اشغال است | `khorshid ui --port 8900` |
| دیمون دو بار روشن شده | `khorshid hotkey --stop` بعد `--daemon` |

---

## ❓ سوالات پرتکرار

**آیا رایگان است؟** بله، کاملاً. موتور آفلاین + Ollama + ابزارها رایگان‌اند؛ فقط اگر مغز ابری (Gemini/OpenAI) بخواهی کلید لازم است (Gemini سهمیه رایگان سخاوتمندانه‌ای دارد).

**بدون اینترنت کار می‌کند؟** بله — موتور `mock` آفلاین کارهای فایل/شل/محاسبات/تودو/حافظه را انجام می‌دهد. قیمت/هوا/وب/تلگرام طبیعتاً اینترنت می‌خواهند.

**روی ویندوز کار می‌کند؟** بله — نصب با `install.ps1`. پوش‌تو‌تاک، صدا و دسکتاپ روی ویندوز ساپورت می‌شوند.

**چه فرقی با OpenJarvis دارد؟** OpenJarvis اسکلت آکادمیک است؛ خورشید نهایی فارسی‌اول است، موتور آفلاین فارسی‌فهم دارد، مرورگر/دسکتاپ/صدا/تلگرام/پوش‌تو‌تاک واقعی دارد و out-of-the-box «هر کاری» انجام می‌دهد.

**چطور ابزار/ایجنت خودم را اضافه کنم؟** ابزار: ۲۰ خط با دکوراتور (بالا). ایجنت: کلاس جدید روی `BaseAgent` + یک خط `@AgentRegistry.register`.

---

## 🏛️ معماری (الگو از OpenJarvis)

```
ultimate_khorshid/
├── core/          Registry • Types • Config • EventBus • tracing • cost • context • retry • jsonx • control • checkpoint • blackboard • vault • parallel • sandbox
├── intelligence/  Model Catalog • Heuristic Router
├── engine/        mock • ollama • gemini • openai_compat (+ discovery)
├── tools/         ۵۶ ابزار در ۱۳ ماژول + ToolExecutor (retry/trace/cancel/fallback)
├── agents/        ۱۰ ایجنت روی BaseAgent (+ ۴ نام مستعار) — شامل supervisor چندایجنتی
├── skills/        SkillManager + ۹ مهارت داخلی (agentskills.io)
├── channels/      📱 تلگرام (polling با stdlib) روی ChannelRegistry
├── hotkey/        پوش‌تو‌تاک سراسری + مدیریت دیمون (pid/log/stop/status)
├── voice/         STT زنجیره‌ای (محلی←Gemini←Google) + TTS + wake-word + حلقه گفت‌وگو
├── memory/        SQLite+FTS5 • chunking • ingest
├── scheduler/     TaskStore + TaskScheduler
├── security/      secret/PII/injection scanner • spotlighting • audit log • guardrails
├── server/        داشبورد فارسی + ۲۰ مسیر API + سازگار با OpenAI (stdlib)
├── cli/           khorshid با ۲۴ دستور (traces/costs/vault/eval/checkpoints/wake) + ویزارد setup
├── prompts/       پرسونای فارسی خورشید
├── evals/         سوئیت رگرسیون آفلاین (۱۰ تسک)
└── runtime.py     کارخانه یک‌خطی ساخت ایجنت آماده
```

**ایده‌های گرفته‌شده از OpenJarvis:** رجیستری دکوراتوری (`RegistryBase[T]`)، `BaseAgent` با متدهای کمکی، `ToolExecutor` با ایونت‌باس، `ToolSpec` سازگار با OpenAI، پنج ستون Intelligence/Engine/Agents/Tools+Memory/Learning، مهارت‌های agentskills.io، حافظه SQLite/FTS5، ایجنت‌های react/orchestrator/openhands/deep_research/operative.

**چیزهایی که خورشید نهایی اضافه/بهتر کرده:** فارسی اول (پرسونا، شمسی، موتور mock فارسی‌فهم قاعده‌محور)، صفر وابستگی در هسته (حتی سرور و موتورها با stdlib)، ایجنت `computer` یکپارچه، `datetime` شمسی بدون کتابخانه، CLI یکپارچه با setup/schedule/skill/doctor/telegram، پوش‌تو‌تاک سراسری، ربات تلگرام، حل خودکار آزمون سایت، ویزارد نصب، اجرای واقعی کامپیوتری out-of-the-box.

---

## 🗺️ نقشه راه

- [x] موتور `gemini` با function calling
- [x] TTS/STT فارسی (صوت خورشید: `khorshid voice`)
- [x] کانال تلگرام 📱
- [x] پوش‌تو‌تاک سراسری 🎙️
- [x] هواشناسی و اعلان دسکتاپ
- [x] ویزارد نصب
- [ ] موتور `anthropic` (فعلاً via openrouter پوشش داده می‌شود)
- [ ] حافظه برداری FAISS (اختیاری)
- [x] سندباکس Docker برای اجرای کد (۲.۱: docker ← firejail ← restricted)
- [x] ردیابی/هزینه/چک‌پوینت/استریم/سوپروایزر/Vault (۲.۱)
- [ ] ارسال عکس/فایل در ربات تلگرام

---

## 📄 لایسنس

Apache-2.0 — آزاد برای استفاده شخصی و تجاری.

*ساخته‌شده با ❤️ برای فارسی‌زبان‌ها — «چشم قربان.»*
</div>
