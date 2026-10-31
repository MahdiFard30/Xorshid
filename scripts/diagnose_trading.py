"""Capture read-only feed and verified-outcome evidence. Never sends orders.

Writes only into the requested output folder. No learner, runtime or terminal
configuration is changed. Each source snapshot is preserved alongside hashes.
"""
import argparse
from collections import defaultdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys
import time
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ultimate_khorshid.tools.trade_memory import TradeMemory


def aggregate(rows):
    closed=[r for r in rows if r['closed_complete']]
    verified=[r for r in closed if r['learning_eligible']]
    gains=sum(max(0,r['net']) for r in closed)
    losses=-sum(min(0,r['net']) for r in closed)
    return {'closed':len(closed),'wins':sum(r['net']>0 for r in closed),
            'net':round(sum(r['net'] for r in closed),2),
            'profit_factor':gains/losses if losses else None,
            'verified_for_learning':len(verified),
            'mean_verified_r':sum(r['normalized_reward'] for r in verified)/len(verified) if verified else None,
            'incomplete':sum(not r['closed_complete'] for r in rows)}


def capture(root,terminal,output,hours=24):
    now=time.time();output.mkdir(parents=True,exist_ok=False)
    result={'captured_utc':now,'since_utc':now-hours*3600,'hours':hours,
            'orders_sent':False,'runtime_changed':False,'symbols':{},'limitations':[
                'Snapshot and journals are not an atomic cross-process capture.',
                'Metrics use recorded closed trades; missing records are reported, not reconstructed.',
                'Historical periods may contain different code and learning policies.',
                'Valid OHLC and account fields do not independently verify a broker feed.',
                'Corrupt historical excursion samples are retained; they cannot justify exit tuning.']}
    log=terminal.parents[2]/'logs'/(datetime.fromtimestamp(now,ZoneInfo('Europe/Stockholm')).strftime('%Y%m%d')+'.log')
    if log.exists():
        lines=log.read_text(encoding='utf-16',errors='replace').splitlines()[-1000:]
        invalid=[line for line in lines if 'old tick' in line or 'old last price' in line]
        result['terminal_log_evidence']={'file':str(log),'scope':'last 1000 log lines',
            'old_quote_messages':len(invalid),'examples':invalid[-10:]}
    for symbol in ('XAUUSD','EURUSD','USDJPY'):
        raw=(terminal/symbol/'khorshid_demo_snapshot.json').read_bytes()
        snapshot=json.loads(raw.decode('utf-8-sig'))
        (output/(symbol+'-snapshot.json')).write_bytes(raw)
        state=json.loads((root/'.khorshid-multi'/symbol/'state.json').read_text())
        outcomes=TradeMemory.read_only(root/'.khorshid-multi'/symbol/'trade_memory.sqlite').outcomes(snapshot)
        offset=snapshot.get('broker_utc_offset_seconds')
        if not isinstance(offset,(int,float)):
            raise ValueError('Broker offset missing; cannot attribute outcomes to requested period')
        rows=[r for r in outcomes.values() if r.get('closed_time_server') is not None
              and now-hours*3600<=r['closed_time_server']-offset<=now]
        groups=defaultdict(list)
        for row in rows:groups[row['strategy']].append(row)
        stored={str(t) for row in outcomes.values() for t in row['deal_tickets']}
        missing=[d['ticket'] for d in snapshot.get('deals',[]) if str(d['ticket']) not in stored]
        result['symbols'][symbol]={
            'snapshot_sha256':hashlib.sha256(raw).hexdigest(),
            'snapshot_age_seconds':now-snapshot['generated_utc'],
            'quote_age_seconds':snapshot.get('tick_age_seconds'),
            'account_valid_does_not_imply_fresh_symbol_quote':True,
            'terminal':{k:snapshot.get(k) for k in ('login','demo','connected','ea_version','algo_enabled','halted',
                'stopped','account_data_valid','account_data_note','bid','ask','tick_age_seconds',
                'balance','equity','own_positions','total_positions','positions')},
            'worker':{k:state.get(k) for k in ('id','status','started_utc','last_snapshot_utc','last_ack','error')},
            'closed_in_window':aggregate(rows),
            'by_strategy':{name:aggregate(items) for name,items in groups.items()},
            'snapshot_deals_not_yet_in_journal':missing,
            'outcomes':rows}
    path=output/'diagnosis.json'
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--hours',type=float,default=24)
    p.add_argument('--terminal',type=Path,default=Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5/MQL5/Files/khorshid_multi')
    args=p.parse_args()
    if not 0<args.hours<=8760:p.error('hours must be positive and at most one year')
    r=capture(ROOT,args.terminal,args.output,args.hours)
    print(json.dumps({s:{'metrics':v['closed_in_window'],'strategies':v['by_strategy'],
        'terminal':v['terminal'],'unrecorded_deals':v['snapshot_deals_not_yet_in_journal']}
        for s,v in r['symbols'].items()},ensure_ascii=False,indent=2))
