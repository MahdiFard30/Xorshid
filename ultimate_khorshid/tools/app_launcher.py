"""Resolve installed Linux applications without interpreting desktop Exec fields."""
import configparser
import os
from pathlib import Path
import re
import shutil
import subprocess


def norm(value):
    return re.sub(r'\s+', ' ', value.lower().replace('ي', 'ی').replace('ك', 'ک').replace('۵', '5').replace('\u200c', ' ')).strip()


def catalog():
    roots = [Path(os.environ.get('XDG_DATA_HOME') or Path.home()/'.local/share')]
    roots += [Path(p) for p in (os.environ.get('XDG_DATA_DIRS') or '/usr/local/share:/usr/share').split(':') if p]
    roots += [Path.home()/'.local/share/flatpak/exports/share', Path('/var/lib/flatpak/exports/share'), Path('/var/lib/snapd/desktop')]
    seen, entries = set(), []
    for root in roots:
        directory = root/'applications'
        for path in sorted(directory.glob('**/*.desktop')):
            identifier = str(path.relative_to(directory)).replace('/', '-')
            if identifier in seen:
                continue
            seen.add(identifier)
            try:
                parser = configparser.ConfigParser(interpolation=None, strict=False)
                parser.optionxform = str
                parser.read(path, encoding='utf-8')
                entry = parser['Desktop Entry']
                if entry.get('Type') != 'Application' or entry.get('Hidden', '').lower() == 'true':
                    continue
                if not entry.get('Name'):
                    continue
                names = [v for k, v in entry.items() if k == 'Name' or k.startswith('Name[')]
                generic = [v for k, v in entry.items() if k == 'GenericName' or k.startswith('GenericName[')]
                keywords = [word for k, v in entry.items() if k == 'Keywords' or k.startswith('Keywords[')
                            for word in v.split(';') if word]
                speech_names = list(dict.fromkeys(entry[k] for k in ('Name', 'Name[fa]', 'Name[en]') if entry.get(k)))
                entries.append(dict(id=identifier, name=entry['Name'], names=names, path=str(path),
                    generic_names=generic, keywords=keywords, speech_names=speech_names,
                    no_display=entry.get('NoDisplay', '').lower() == 'true',
                    snap_instance=entry.get('X-SnapInstanceName', ''),
                    snap_app=entry.get('X-SnapAppName', '')))
            except (OSError, UnicodeError, configparser.Error, KeyError):
                continue
    return entries


ALIASES = {
    'دیسکورد': ['discord', 'discord_discord', 'com.discordapp.Discord'],
    'دیس کورد': ['discord', 'discord_discord', 'com.discordapp.Discord'],
    'دیسکرد': ['discord', 'discord_discord', 'com.discordapp.Discord'],
    'تلگرام': ['telegram', 'telegram-desktop', 'org.telegram.desktop'],
    'کروم': ['google-chrome', 'google chrome'],
    'فایرفاکس': ['firefox', 'firefox web browser', 'org.mozilla.firefox'],
    'وی اس کد': ['code', 'visual studio code'],
    'متاتریدر': ['metatrader 5', 'mt5'],
}
MT5 = {'متاتریدر', 'متاتریدر 5', 'متا تریدر', 'متا تریدر 5', 'metatrader', 'metatrader 5', 'metatrader5', 'mt5'}


class AppNotFoundError(ValueError):
    code = 'app_not_found'


class AppAmbiguousError(ValueError):
    code = 'app_ambiguous'


def _keys(app):
    return {norm(app['id']), norm(app['id'].removesuffix('.desktop')), *map(norm, app['names'])}


def _tokens(text):
    return set(re.findall(r'[^\W_]+', norm(text)))


def _ordered(apps):
    return sorted(apps, key=lambda a: (bool(a.get('no_display')), norm(a['name']), a['id']))


def find_apps(query='', *, apps=None):
    """Exact installed names first, then whole words; no fuzzy auto-launching."""
    apps = catalog() if apps is None else apps
    query = norm(query)
    if not query:
        return _ordered(apps)
    queries = {query, *map(norm, ALIASES.get(query, []))}
    exact = [a for a in apps if queries & _keys(a)]
    if exact:
        return _ordered(exact)
    words = _tokens(query)
    if not words or not any(len(word) >= 3 for word in words):
        return []
    matches = [a for a in apps if any(words <= _tokens(value) for value in a['names'])]
    if not matches:
        matches = [a for a in apps if words <= _tokens(a['id'])]
    return _ordered(matches)


def search_apps(query='', *, offset=0, limit=100):
    """Paginated discovery includes desktop-provided categories and keywords."""
    apps = catalog()
    matches = find_apps(query, apps=apps)
    words = _tokens(query)
    if query and words:
        seen = {a['id'] for a in matches}
        matches += _ordered([a for a in apps if a['id'] not in seen and any(
            words <= _tokens(value) for value in a.get('generic_names', []) + a.get('keywords', []))])
    total = len(matches)
    records = [{'id': a['id'], 'name': a['name'],
                'names': a.get('speech_names', a['names'][:3])}
               for a in matches[offset:offset + limit]]
    return {'apps': records, 'total': total, 'offset': offset,
            'next_offset': offset + len(records) if offset + len(records) < total else None}


def speech_vocabulary():
    """Bounded hints derived from all installed apps, including future installs."""
    apps = _ordered(catalog())
    words = [value[:80] for app in apps for value in app.get('speech_names', [app['name']]) if value]
    for spoken, aliases in ALIASES.items():
        queries = {norm(spoken), *map(norm, aliases)}
        for app in apps:
            keys = {norm(app['id'].removesuffix('.desktop')), *map(norm, app['names'])}
            if queries & keys:
                words.extend([spoken, app['name'][:80]])
                break
    return list(dict.fromkeys(words))[:192]


def resolve(target):
    """Return argv/env; resolution itself never starts a process."""
    target = target.strip()
    if not target:
        raise ValueError('نام برنامه خالی است.')
    name = norm(target)
    if name in MT5:
        bases = [Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5']
        configured = os.environ.get('KHORSHID_MT5_DATA_DIR')
        if configured:
            bases.insert(0, Path(configured).expanduser())
        for base in bases:
            exe = base/'terminal64.exe'
            if exe.is_file():
                drive = next((p for p in exe.parents if p.name == 'drive_c'), None)
                wine = shutil.which('wine') or shutil.which('wine64')
                if not wine:
                    raise ValueError('متاتریدر پیدا شد اما دستور wine در دسترس نیست.')
                if drive is not None:
                    env = os.environ.copy()
                    env['WINEPREFIX'] = str(drive.parent)
                    return [wine, str(exe)], env
    matches = find_apps(name)
    if len(matches) > 1:
        raise AppAmbiguousError('چند برنامه پیدا شد: ' + ', '.join(a['name']+' ('+a['id']+')' for a in matches))
    if matches:
        # Use installed Snap metadata, rather than per-application exceptions.
        instance, app = matches[0].get('snap_instance', ''), matches[0].get('snap_app', '')
        if re.fullmatch(r'[a-z0-9][a-z0-9-]*(?:_[a-z0-9-]+)?', instance) and re.fullmatch(r'[a-z0-9][a-z0-9-]*', app):
            snap = shutil.which('snap')
            if snap:
                command = instance if app == instance.split('_', 1)[0] else instance+'.'+app
                return [snap, 'run', command], None
        gio = shutil.which('gio')
        if gio:
            return [gio, 'launch', matches[0]['path']], None
        raise ValueError('برنامه پیدا شد اما gio برای اجرای میانبر نصب نیست.')
    path = Path(target).expanduser()
    if path.exists():
        # Document opening must not become a second command execution API.
        if path.is_file() and (os.access(path, os.X_OK) or path.suffix.lower() in {
                '.desktop', '.sh', '.bash', '.py', '.js', '.exe', '.bat', '.cmd', '.ps1', '.appimage'}):
            raise ValueError('اجرای فایل کد از open_app مجاز نیست؛ از ابزار اجرای کد با تأیید استفاده کن.')
        opener = shutil.which('xdg-open')
        if not opener:
            raise ValueError('xdg-open در دسترس نیست.')
        return [opener, str(path.resolve())], None
    raise AppNotFoundError('نام دقیق نصب‌شده برای «' + target + '» پیدا نشد؛ فهرست برنامه‌ها باید بررسی شود.')


def launch(target):
    argv, env = resolve(target)
    process = subprocess.Popen(argv, env=env, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
    try:
        code = process.wait(timeout=0.5)
        if code:
            raise RuntimeError(f'اجرای برنامه با کد {code} ناموفق بود.')
    except subprocess.TimeoutExpired:
        pass
    return f'درخواست اجرای {target} ارسال شد؛ نمایش پنجره هنوز بررسی نشده است.'
