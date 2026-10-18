"""Interactive, hidden Groq key entry; validate before atomically saving config."""
import argparse
import copy
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import urllib.error
import urllib.request
import warnings

from ultimate_khorshid.core.config import tomllib
from ultimate_khorshid.engine.groq import GroqEngine


def _upsert(text, section, key, value):
    lines = text.splitlines(keepends=True)
    start, end = None, len(lines)
    for index, line in enumerate(lines):
        if re.fullmatch(r'\s*\[' + re.escape(section) + r'\]\s*(?:#.*)?', line.rstrip('\r\n')):
            start = index + 1
        elif start is not None and line.lstrip().startswith('['):
            end = index
            break
    rendered = f'{key} = {json.dumps(value, ensure_ascii=False)}\n'
    if start is None:
        return text.rstrip() + f'\n\n[{section}]\n' + rendered
    for index in range(start, end):
        if re.match(r'\s*' + re.escape(key) + r'\s*=', lines[index]):
            lines[index] = rendered
            return ''.join(lines)
    if end > 0 and not lines[end - 1].endswith('\n'):
        lines[end - 1] += '\n'
    lines.insert(end, rendered)
    return ''.join(lines)


def save_key(path, key):
    """Preserve existing settings and other keys; replace only the Groq key."""
    path = Path(path)
    old = path.read_text(encoding='utf-8') if path.exists() else ''
    if tomllib is None:
        raise RuntimeError('TOML parser unavailable')
    original = tomllib.loads(old)
    # Existing flat keys take precedence in the config loader. Update them
    # as well when present so an older credential cannot shadow the new one.
    new = _upsert(old, 'engine.groq', 'api_key', key)
    if 'groq_api_key' in original.get('engine', {}):
        new = _upsert(new, 'engine', 'groq_api_key', key)
    parsed = tomllib.loads(new)
    expected = copy.deepcopy(original)
    expected.setdefault('engine', {}).setdefault('groq', {})['api_key'] = key
    if 'groq_api_key' in original.get('engine', {}):
        expected['engine']['groq_api_key'] = key
    if parsed != expected:
        raise RuntimeError('Config validation failed')
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.groq-setup-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(new)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def check_key(key):
    """No generation tokens: verify authentication on Groq's models endpoint."""
    engine = GroqEngine(api_key=key)
    request = urllib.request.Request(engine.base_url + '/models', headers=engine._headers())
    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.loads(response.read())
    if not isinstance(data.get('data'), list):
        raise ValueError('Unexpected models response')


def main(argv=None):
    parser = argparse.ArgumentParser(description='ورود مخفی کلید Groq و تست اتصال')
    parser.add_argument('--keep-open', action='store_true')
    args = parser.parse_args(argv)
    target = Path.home() / '.ultimate-jarvis/config.toml'
    result = 1
    try:
        if not sys.stdin.isatty():
            print('این فرمان را در ترمینال خودت اجرا کن تا کلید مخفی وارد شود.')
            return 1
        print('کلید کامل Groq را بچسبان و Enter بزن؛ هنگام تایپ نمایش داده نمی‌شود.')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            key = getpass.getpass('Groq API key: ').strip()
        if not key or any(char.isspace() for char in key):
            print('کلید خالی است یا فاصله دارد؛ چیزی ذخیره نشد.')
        else:
            check_key(key)
            save_key(target, key)
            print('اتصال تأیید شد. کلید در کانفیگ مشترک خورشید با دسترسی ۶۰۰ ذخیره شد:')
            print(target)
            if os.environ.get('GROQ_API_KEY') and os.environ['GROQ_API_KEY'] != key:
                print('متغیر محیطی GROQ_API_KEY قدیمی است؛ پیش از اجرای خورشید آن را حذف یا به‌روز کن.')
            print('خورشید را ببند و دوباره اجرا کن تا کلید تازه خوانده شود.')
            result = 0
    except urllib.error.HTTPError as exc:
        print(f'سرویس Groq خطای HTTP {exc.code} برگرداند؛ کلید قبلی تغییر نکرد.')
    except (KeyboardInterrupt, EOFError):
        print('\nلغو شد؛ چیزی ذخیره نشد.')
    except Exception:
        # Never display raw HTTP/config exceptions containing credentials.
        print('تست اتصال یا ذخیره‌سازی ناموفق بود؛ جزئیات محرمانه نمایش داده نمی‌شود.')
    finally:
        if args.keep_open and sys.stdin.isatty():
            try:
                input('برای بستن این پنجره Enter بزن...')
            except (EOFError, KeyboardInterrupt):
                pass
    return result


if __name__ == '__main__':
    raise SystemExit(main())
