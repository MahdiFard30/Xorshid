"""Install the independent read-only calendar service; does not start a service.

The trading EA installer remains separate and refuses active trading terminals.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT=Path(__file__).resolve().parents[1]
NAMES=('KhorshidNewsBridge.mq5','KhorshidNewsBridge.ex5')


def install(terminal):
    artifacts=ROOT/'mt5'
    manifest=json.loads((artifacts/'recovery-build.json').read_text())
    expected=(manifest['news_bridge_source_sha256'],manifest['news_bridge_binary_sha256'])
    contents=[(artifacts/name).read_bytes() for name in NAMES]
    if any(hashlib.sha256(data).hexdigest()!=digest for data,digest in zip(contents,expected)):
        raise ValueError('Calendar bridge build hashes do not match')
    target=terminal/'MQL5/Services'
    if not (terminal/'MQL5').is_dir():
        raise ValueError('Existing MT5 MQL5 directory required')
    target.mkdir(exist_ok=True)
    for name,data in zip(NAMES,contents):
        path=target/name
        if path.exists() and path.read_bytes()!=data:
            raise ValueError('Existing calendar bridge differs; preserve it before replacing')
    written=[]
    try:
        for name,data in zip(NAMES,contents):
            path=target/name
            if path.exists():continue
            fd,temp=tempfile.mkstemp(prefix='.khorshid-news-',dir=target)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(data);stream.flush();os.fsync(stream.fileno())
                os.replace(temp,path)
                written.append(path)
            finally:
                if os.path.exists(temp):os.unlink(temp)
    except Exception:
        for path in written:path.unlink(missing_ok=True)
        raise
    return {'installed':True,'directory':str(target),'started':False,'trade_operations':False,
            'instruction':'In MT5 Navigator, refresh Services, add KhorshidNewsBridge and start it.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install',action='store_true')
    args=parser.parse_args()
    terminal=Path(os.environ.get('KHORSHID_MT5_DATA_DIR',str(Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5'))).expanduser()
    result=install(terminal) if args.install else {'terminal':str(terminal),'instruction':'Use --install to copy the verified read-only service.'}
    print(json.dumps(result,ensure_ascii=False))


if __name__=='__main__':main()
