"""Install the reviewed recovery EA only while MT5 and its workers are stopped."""
import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import tempfile
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT/'mt5'
NAMES = ('RestartPolicy.mqh','KhorshidMultiTrader.mq5','KhorshidMultiTrader.ex5')


def terminal_running():
    # IDE/sandbox process namespaces may hide the desktop terminal process.
    # A recently published EA snapshot is independent evidence that MT5 runs.
    data=Path(os.environ.get('KHORSHID_MT5_DATA_DIR',str(Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5'))).expanduser()/'MQL5/Files'
    candidates=list((data/'khorshid_multi').glob('*/khorshid_demo_snapshot.json'))+[data/'khorshid_demo_snapshot.json']
    for path in candidates:
        try:
            if -5 <= time.time()-path.stat().st_mtime <= 20:
                return True
        except FileNotFoundError:
            pass
    for entry in Path('/proc').iterdir():
        if not entry.name.isdigit(): continue
        try:
            args=(entry/'cmdline').read_bytes().split(b'\0')
            if any(arg.decode(errors='replace').lower().replace('\\','/').rsplit('/',1)[-1]=='terminal64.exe' for arg in args):
                return True
        except OSError:
            continue
    return False


def workers_running():
    paths = list((ROOT/'.khorshid-multi').glob('*/runner.lock')) + [ROOT/'.khorshid-demo/runner.lock']
    for path in paths:
        if not path.is_file(): continue
        with path.open('r') as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                fcntl.flock(lock,fcntl.LOCK_UN)
            except BlockingIOError:
                return True
    return False


def checked_artifacts():
    data=json.loads((ARTIFACTS/'recovery-build.json').read_text())
    for field,name in [('source_sha256',NAMES[1]),('binary_sha256',NAMES[2]),('policy_sha256',NAMES[0])]:
        if hashlib.sha256((ARTIFACTS/name).read_bytes()).hexdigest()!=data[field]:
            raise ValueError('Build files changed; compile and validate again')
    return data


def _replace(path, data):
    fd,name=tempfile.mkstemp(prefix='.khorshid-install-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name): os.unlink(name)


def install(target):
    build=checked_artifacts()
    if terminal_running() or workers_running():
        raise ValueError('متاتریدر یا سرویس معامله هنوز فعال است؛ نصب انجام نشد.')
    if not target.is_dir(): raise ValueError('پوشهٔ Experts پیدا نشد.')
    current=target/NAMES[1]
    if current.exists() and hashlib.sha256(current.read_bytes()).hexdigest() not in (
            build['previous_source_sha256'],build['source_sha256']):
        raise ValueError('اکسپرت نصب‌شده با نسخهٔ بررسی‌شده فرق دارد؛ جایگزین نشد.')
    backup_root=ROOT/'local-backups'/'mt5'
    backup_root.parent.mkdir(mode=0o700,exist_ok=True)
    backup_root.mkdir(mode=0o700,exist_ok=True)
    backup=Path(tempfile.mkdtemp(prefix=datetime.now(ZoneInfo('Europe/Stockholm')).strftime('%Y%m%d-%H%M%S-'),dir=backup_root))
    previous={name:(target/name).read_bytes() if (target/name).exists() else None for name in NAMES}
    for name,data in previous.items():
        if data is not None:
            (backup/name).write_bytes(data)
    try:
        # Header and source first, executable last. No terminal can load a
        # partially copied executable; user/risk stop markers are never touched.
        for name in NAMES:
            _replace(target/name,(ARTIFACTS/name).read_bytes())
    except Exception:
        for name,data in previous.items():
            if data is None: (target/name).unlink(missing_ok=True)
            else: _replace(target/name,data)
        raise
    return backup


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args()
    target=Path(os.environ.get('KHORSHID_MT5_DATA_DIR',str(Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5'))).expanduser()/'MQL5/Experts'
    try:
        checked_artifacts()
        if not args.install:
            print('فایل‌های نسخهٔ '+str(checked_artifacts()['ea_version'])+' تأیید شدند؛ نصب انجام نشد.')
            print('متاتریدر فعال است:',terminal_running(),'؛ سرویس معامله فعال است:',workers_running())
            print('برای نصب در زمان توقف هر دو: .venv/bin/python scripts/install_mt5_recovery.py --install')
            return 0
        print('نسخهٔ جدید نصب شد؛ پشتیبان نسخهٔ قبلی:',install(target))
        print('این نصب توقف دستی یا محدودیت زیان را پاک نمی‌کند و معامله را شروع نمی‌کند.')
        return 0
    except (OSError,ValueError,KeyError) as exc:
        print('نصب انجام نشد:',exc)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
