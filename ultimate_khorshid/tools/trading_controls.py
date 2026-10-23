"""Shared, inspectable trading settings. Missing files preserve legacy behavior."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile

DEFAULTS={
    'cooldown_bars':1,'stop_cluster_enabled':True,'stop_window_bars':8,
    'stop_lock_bars':4,'symbol_stop_limit':2,'account_stop_limit':3,
    'news_entry_block_enabled':True,'news_before_minutes':30,'news_after_minutes':15,
    'max_positions':1,'entry_window_max_seconds':300,'entry_window_fraction':.5,
    'max_hold_bars':24,'daily_loss_fraction':.02,'peak_drawdown_fraction':.10,
    'portfolio_cap_fraction':.005,'margin_cap_fraction':.20,'spread_atr_fraction':.10,
    'weekly_close_lead_seconds':600,
}


def read(root):
    path=Path(root)/'configs/trading_controls.json'
    if not path.exists():return dict(DEFAULTS)
    data=json.loads(path.read_text())
    if data.get('schema')!=1:raise ValueError('Unknown trading controls schema')
    values={**DEFAULTS,**data.get('settings',{})}
    if set(values)!=set(DEFAULTS):raise ValueError('Unknown trading control')
    for key,default in DEFAULTS.items():
        value=values[key]
        if type(default) is bool:
            if type(value) is not bool:raise ValueError('Invalid boolean control '+key)
        elif type(value) not in (int,float) or not 0<=value<=100000:
            raise ValueError('Invalid numeric control '+key)
        if type(default) is int and type(value) is not int:raise ValueError('Integer required '+key)
    for key in ('entry_window_fraction','daily_loss_fraction','peak_drawdown_fraction',
                'portfolio_cap_fraction','margin_cap_fraction','spread_atr_fraction'):
        if not 0<values[key]<=1:raise ValueError('Invalid fraction '+key)
    if values['max_positions'] not in (1,2):raise ValueError('Unsupported native position capacity')
    return values


def revision(values):
    return hashlib.sha256(json.dumps(values,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def publish(root,terminal):
    values=read(root);tag=revision(values)
    path=Path(terminal)/'MQL5/Files/khorshid_multi/shared-controls.tsv'
    path.parent.mkdir(parents=True,exist_ok=True)
    body='revision\t'+tag+'\n'+''.join(k+'\t'+str(int(v) if type(v) is bool else v)+'\n' for k,v in values.items())
    fd,name=tempfile.mkstemp(dir=path.parent,prefix='.controls-')
    try:
        with os.fdopen(fd,'w') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)
    return tag


def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['show','publish'])
    args=parser.parse_args();root=Path(__file__).resolve().parents[2]
    values=read(root)
    if args.action=='publish':
        terminal=Path(os.environ.get('KHORSHID_MT5_DATA_DIR',str(Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5')))
        publish(root,terminal)
    print(json.dumps({'settings':values,'revision':revision(values)},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
