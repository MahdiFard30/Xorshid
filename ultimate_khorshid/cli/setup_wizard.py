"""ویزارد نصب تعاملی — `khorshid setup`.

قدم‌به‌قدم: انتخاب موتور → کلید API → اکستراها → هات‌کی → ذخیره کانفیگ.
با دادن همه گزینه‌ها + ‎--yes‎ کاملاً غیرتعاملی می‌شود (مناسب اسکریپت و تست).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

ENGINES = {
    "1": ("mock", "mock/smart", "آفلاین، بدون نیاز به اینترنت/کلید (پیشنهاد شروع)"),
    "2": ("ollama", "ollama/qwen2.5:7b", "مدل لوکال با Ollama — حریم خصوصی کامل"),
    "3": ("gemini", "gemini/gemini-2.0-flash", "مغز ابری گوگل — رایگان، نیاز به API key"),
    "4": ("openai_compat", "openai/gpt-4o-mini", "OpenAI / DeepSeek / OpenRouter... (نیاز به API key)"),
}
BY_NAME = {e: (k, m, d) for k, (e, m, d) in ENGINES.items()}


def _ask(prompt: str, default: str = "") -> str:
    try:
        v = input(f"{prompt}" + (f" [{default}]" if default else "") + ": ").strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(1)
    return v or default


def _yes(prompt: str, default: bool = True) -> bool:
    suf = "Y/n" if default else "y/N"
    v = _ask(f"{prompt} ({suf})").strip().lower()
    if not v:
        return default
    return v in ("y", "yes", "بله", "آره", "1")


def build_config_toml(engine: str, model: str, api_key: str = "",
                      base_url: str = "") -> str:
    """ساخت متن کانفیگ TOML معتبر برای موتور انتخاب‌شده."""
    key_line = f'api_key = "{api_key}"' if api_key else "# api_key = \"...\"  # یا متغیر محیطی"
    extra = ""
    if engine == "gemini":
        extra = ('\n[engine.gemini]\nmodel = "gemini-2.0-flash"\n'
                 'tts_model = "gemini-2.5-flash-preview-tts"\nvoice = "Kore"\n'
                 f"{key_line}\n")
    elif engine == "openai_compat":
        extra = ('\n[engine.openai]\n'
                 f'base_url = "{base_url or "https://api.openai.com/v1"}"\n'
                 f'model = "{model.split("/", 1)[-1]}"\n{key_line}\n')
    elif engine == "ollama":
        extra = ('\n[engine.ollama]\nhost = "http://localhost:11434"\n'
                 f'model = "{model.split("/", 1)[-1]}"\n')
    return f"""# ساخته‌شده با: khorshid setup
[intelligence]
default_model = "{model}"
preferred_engine = "{engine}"
temperature = 0.7
max_tokens = 2000

[agent]
default_agent = "computer"
max_turns = 12
tools = "*"
persona = "khorshid"
language = "fa"

[engine]
default = "{engine}"
{extra}
[tools]
confirm_dangerous = true

[server]
host = "127.0.0.1"
port = 8899
agent = "computer"
"""


def write_config(text: str, base_dir: Path) -> Path:
    base_dir.mkdir(parents=True, exist_ok=True)
    fp = base_dir / "config.toml"
    fp.write_text(text, encoding="utf-8")
    try:
        os.chmod(fp, 0o600)  # کانفیگ ممکن است کلید داشته باشد
    except Exception:
        pass
    return fp


def repo_root() -> Optional[Path]:
    p = Path(__file__).resolve()
    for parent in [p.parent.parent.parent, p.parent.parent]:
        if (parent / "pyproject.toml").exists():
            return parent
    return None


def pip_install(extras: str) -> bool:
    root = repo_root()
    if not root:
        print("⚠️ پوشه سورس پیدا نشد؛ دستی نصب کن:")
        print(f'   pip install -e ".[{extras}]"')
        return False
    target = f".[{extras}]" if extras and extras != "none" else "."
    print(f"📦 در حال نصب: pip install -e \"{target}\" ...")
    try:
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-e", target],
                           cwd=str(root), timeout=900)
        return r.returncode == 0
    except Exception as e:
        print(f"❌ خطای نصب: {e}")
        return False


def run_setup(engine: Optional[str] = None, api_key: Optional[str] = None,
              extras: Optional[str] = None, hotkey: Optional[str] = None,
              yes: bool = False, base_dir: Optional[Path] = None,
              install: bool = True) -> int:
    """اجرای ویزارد. همه پارامترها اختیاری‌اند (سؤال می‌شود اگر نباشند)."""
    base = Path(base_dir) if base_dir else Path.home() / ".ultimate-jarvis"
    print("🧙 ویزارد نصب خورشید نهایی\n")
    print(f"   پایتون: {sys.version.split()[0]} (نیاز: 3.10+)")
    if sys.version_info < (3, 10):
        print("❌ پایتون قدیمی است! اول پایتون 3.10+ نصب کن.")
        return 1

    # ۱) موتور
    if engine not in BY_NAME:
        print("\n🧠 کدام مغز؟")
        for k, (e, m, d) in ENGINES.items():
            print(f"   {k}) {e:13} {m:28} — {d}")
        engine = _ask("انتخاب", "1" if not yes else engine or "1")
        if engine in ENGINES:
            engine = ENGINES[engine][0]
        if engine not in BY_NAME:
            engine = "mock"
    _, model, _ = BY_NAME[engine]
    print(f"✅ موتور: {engine} ({model})")

    # ۲) کلید
    key = api_key or ""
    base_url = ""
    if engine in ("gemini", "openai_compat") and not key and not yes:
        if engine == "gemini":
            print("🔑 کلید رایگان Gemini از: https://aistudio.google.com")
        key = _ask("کلید API (خالی = بعداً با متغیر محیطی)")
    if engine == "openai_compat" and not yes:
        base_url = _ask("آدرس API", "https://api.openai.com/v1")

    # ۳) اکستراها
    if extras is None and not yes:
        print("\n📦 امکانات اضافه (با کاما جدا کن؛ all = همه):")
        print("   all / server / browser / desktop / voice / hotkey / none")
        extras = _ask("انتخاب", "none")
    extras = (extras or "none").strip().lower()
    if extras not in ("none", ""):
        ok_install = True
        if not yes:
            ok_install = _yes(f"نصب خودکار اکستراهای [{extras}] با pip؟", True)
        if ok_install and install:
            pip_install(extras)
        if "browser" in extras or "all" in extras:
            do_pw = yes or _yes("نصب مرورگر Chromium برای Playwright؟", True)
            if do_pw and install:
                print("🌐 در حال نصب Chromium ...")
                try:
                    subprocess.run([sys.executable, "-m", "playwright",
                                    "install", "chromium"], timeout=900)
                except Exception as e:
                    print(f"⚠️ نصب Chromium نشد: {e} — بعداً دستی بزن.")

    # ۴) هات‌کی
    if hotkey is None and not yes:
        hotkey = _ask("⌨️ کلید پوش‌تو‌تاک", "ctrl")
    try:
        from ultimate_khorshid.core.settings import set_settings
        set_settings(hotkey=hotkey or "ctrl")
        print(f"✅ پوش‌تو‌تاک: {hotkey or 'ctrl'}")
    except Exception as e:
        print(f"⚠️ ذخیره هات‌کی نشد: {e}")

    # ۵) کانفیگ
    fp = write_config(build_config_toml(engine, model, key, base_url), base)
    print(f"✅ کانفیگ ذخیره شد: {fp}")

    print("\n🎉 تمام شد! قدم‌های بعد:")
    print("   khorshid doctor          # بررسی سلامت")
    print("   khorshid chat            # گفت‌وگو")
    print("   khorshid ui              # داشبورد وب فارسی")
    print("   khorshid hotkey --daemon # پوش‌تو‌تاک سراسری")
    if engine == "ollama":
        print(f"\n💡 یادت نره: ollama pull {model.split('/', 1)[-1]}")
    return 0


def list_extras() -> List[str]:
    return ["all", "server", "browser", "desktop", "voice", "hotkey", "test", "none"]
