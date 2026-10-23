"""Inspect effective controls/performance or create and verify restorable backups."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))


def backup(root,target):
    root,target=Path(root),Path(target)
    target.mkdir(parents=True,exist_ok=False)
    records=[]
    for folder in ('.khorshid-multi','.khorshid-research','configs'):
        for p in sorted((root/folder).rglob('*')):
            if not p.is_file() or p.suffix in ('.lock','.tmp') or p.name.endswith(('-wal','-shm')):continue
            relative=p.relative_to(root);dest=target/relative;dest.parent.mkdir(parents=True,exist_ok=True)
            if p.suffix=='.sqlite':
                with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(dest) as dst:
                    src.backup(dst)
            else:shutil.copy2(p,dest)
            records.append({'path':str(relative),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest()})
    (target/'backup-manifest.json').write_text(json.dumps({'schema':1,'created_utc':time.time(),'files':records},indent=2)+'\n')
    return verify(target)


def verify(target):
    target=Path(target);manifest=json.loads((target/'backup-manifest.json').read_text())
    for row in manifest['files']:
        p=target/row['path']
        if not p.resolve().is_relative_to(target.resolve()):raise ValueError('Invalid backup path')
        if hashlib.sha256(p.read_bytes()).hexdigest()!=row['sha256']:raise ValueError('Backup hash mismatch: '+row['path'])
        if p.suffix=='.sqlite':
            with sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True) as con:
                if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Corrupt SQLite backup')
    return {'verified':True,'files':len(manifest['files']),'directory':str(target)}


def restore(backup_dir,target):
    verify(backup_dir);target=Path(target)
    target.mkdir(parents=True,exist_ok=False)
    for row in json.loads((Path(backup_dir)/'backup-manifest.json').read_text())['files']:
        dest=target/row['path'];dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(Path(backup_dir)/row['path'],dest)
    shutil.copy2(Path(backup_dir)/'backup-manifest.json',target/'backup-manifest.json')
    return verify(target)


def performance(root,terminal):
    from ultimate_khorshid.tools.trade_memory import TradeMemory
    groups={};details=[]
    for symbol in ('XAUUSD','EURUSD','USDJPY'):
        s=json.loads((Path(terminal)/'MQL5/Files/khorshid_multi'/symbol/'khorshid_demo_snapshot.json').read_text(encoding='utf-8-sig'))
        memory=TradeMemory.read_only(Path(root)/'.khorshid-multi'/symbol/'trade_memory.sqlite')
        for o in memory.outcomes(s).values():
            details.append(o)
            if not o['closed_complete']:continue
            key='|'.join((o.get('experiment_id') or 'legacy_unlabeled',o.get('learning_regime') or 'legacy_unlabeled',symbol,o['strategy']))
            groups.setdefault(key,[]).append(o['net'])
    summary={k:{'closed':len(v),'net':sum(v),'wins':sum(n>0 for n in v),'losses':sum(n<0 for n in v),
        'mean_win':sum(n for n in v if n>0)/sum(n>0 for n in v) if any(n>0 for n in v) else None,
        'mean_loss':sum(n for n in v if n<0)/sum(n<0 for n in v) if any(n<0 for n in v) else None,
        'mean_net':sum(v)/len(v)} for k,v in groups.items()}
    return {'grouping':'experiment|learning_regime|symbol|strategy','results':summary,'outcomes':details,
            'note':'Observed path metrics cover saved snapshots, not unobserved ticks. Legacy records are retained without invented labels.'}


def main():
    import os
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['rules','performance','backup','verify','restore'])
    p.add_argument('--directory',type=Path);p.add_argument('--target',type=Path);a=p.parse_args()
    if a.action=='rules':
        from ultimate_khorshid.tools.trading_controls import read,revision
        controls=read(ROOT);result={'settings':controls,'revision':revision(controls),
            'execution_policy':json.loads((ROOT/'configs/trading_execution.json').read_text())}
    elif a.action=='performance':
        terminal=Path(os.environ.get('KHORSHID_MT5_DATA_DIR',str(Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5')))
        result=performance(ROOT,terminal)
    elif a.action=='backup':result=backup(ROOT,a.directory)
    elif a.action=='verify':result=verify(a.directory)
    else:result=restore(a.directory,a.target)
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
