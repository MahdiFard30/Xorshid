"""Read-only diagnostics using the same resolved configuration as the runtime."""
from pathlib import Path
import sqlite3


def credentials(cfg):
    from ultimate_khorshid.engine.discovery import get_engine
    # Return booleans only. Never put credentials or their fragments in a report.
    return {name:bool(get_engine(name,cfg).api_key) for name in ('openai','gemini','groq')}


def memory_status(path):
    file=Path(path).expanduser().resolve()
    if not file.is_file():
        return '⚪ پایگاه هنوز ایجاد نشده؛ در اولین استفاده ساخته می‌شود'
    try:
        con=sqlite3.connect(file.as_uri()+'?mode=ro',uri=True,timeout=2)
        try:
            exists=con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories'").fetchone()
            if not exists:
                return '⚪ پایگاه قابل خواندن است؛ جدول حافظهٔ دستی هنوز ایجاد نشده'
            count=con.execute('SELECT COUNT(*) FROM memories').fetchone()[0]
            return f'✅ پایگاه قابل خواندن؛ {count} رکورد حافظهٔ دستی'
        finally:
            con.close()
    except (OSError,sqlite3.Error) as exc:
        return f'⚠️ بررسی پایگاه در این محیط ناموفق بود ({type(exc).__name__})'


def ollama_status(cfg):
    from ultimate_khorshid.engine.discovery import get_engine
    h=get_engine('ollama',cfg).health()
    if h['ok']:
        return '✅ اتصال بررسی شد؛ مدل‌ها: '+str(h.get('models',[]))
    if h.get('errno') in (1,13):
        return '⚠️ اجازهٔ دسترسی شبکه در محیط بررسی وجود ندارد؛ قطع‌بودن سرویس تأیید نشد'
    return '⚠️ از آدرس تنظیم‌شده پاسخی دریافت نشد؛ سرویس یا دسترسی شبکه را بررسی کن'


def personal_tts_status(root):
    root=Path(root)
    if (root/'.tts-venv/bin/python').is_file() and (root/'ultimate_khorshid/assets/my_voice_prompt.wav').is_file():
        return '✅ محیط اجرا و فایل صدای شخصی موجود؛ تولید صدا در این بررسی آزمون نشد'
    return '⚪ محیط اجرا یا فایل صدای شخصی در این پوشه پیدا نشد'


def live_credentials(root):
    """Mirror Live's noninteractive sources, without calling its getpass fallback."""
    from ultimate_khorshid.core.vault import get_secret
    if get_secret('GEMINI_API_KEY') or get_secret('GOOGLE_API_KEY'):
        return True
    file=Path(root)/'.env'
    if file.is_file():
        from dotenv import dotenv_values
        values=dotenv_values(file)
        return bool(values.get('GEMINI_API_KEY') or values.get('GOOGLE_API_KEY'))
    return False
