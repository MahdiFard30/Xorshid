"""Read-only comparison around the 2026-10-23 desktop terminal restart."""
import csv
import io
import json
from pathlib import Path
import sqlite3
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT))
from ultimate_khorshid.tools.mt5_multi import SYMBOLS,select,worker
from ultimate_khorshid.tools.execution_policy import fingerprint
from ultimate_khorshid.tools.trading_controls import read,revision

OUT=Path(__file__).parent;CUT=1792765921;ZONE=ZoneInfo('Europe/Stockholm')
def local(t):return datetime.fromtimestamp(t,ZONE).isoformat() if t else None
def metrics(rows):
    values=[r['net'] for r in rows]
    return {'closed':len(rows),'wins':sum(x>0 for x in values),'losses':sum(x<0 for x in values),
            'net':round(sum(values),2),'mean_net':round(sum(values)/len(values),2) if values else None,
            'mean_risk':round(sum(r['risk_cash'] or 0 for r in rows)/len(rows),2) if values else None}

now=time.time();rows=[];symbols={};all_contexts=[]
for symbol in SYMBOLS:
    select(symbol);s=worker.snapshot();state=worker.state();offset=s['broker_utc_offset_seconds']
    memory=worker.TradeMemory.read_only(worker.storage()/'trade_memory.sqlite')
    outcomes=memory.outcomes(s)
    with sqlite3.connect(worker.storage()/'trade_memory.sqlite') as con:
        contexts=[json.loads(x[0]) for x in con.execute('SELECT data FROM intents')]
        all_contexts+=contexts
    active=[];missing=[]
    for o in outcomes.values():
        if o.get('experiment_id')!='adaptive-controls-20261023':continue
        entries=o['entry_contexts'];entry=min(c['recorded_utc'] for c in entries)
        closed=o.get('closed_time_server');closed=closed-offset if closed else None
        if not o['closed_complete']:
            if not any(str(p['identifier'])==o['position_id'] for p in s['positions']):missing.append(o['position_id'])
            continue
        row={'symbol':symbol,'position_id':o['position_id'],'strategy':o['strategy'],
             'entry_utc':entry,'closed_utc':closed,'entry_local':local(entry),'closed_local':local(closed),
             'net':round(o['net'],2),'risk_cash':o['risk_cash'],'reward_r':o['normalized_reward'],
             'exit_reasons':o['exit_reasons'],'observed_path':o.get('observed_path'),
             'code_revisions':o.get('code_revisions'),'learning_regime':o.get('learning_regime'),
             'cohort':'closed_before_restart' if closed<CUT else 'carried_into_restart' if entry<CUT else 'opened_after_restart'}
        rows.append(row);active.append(row)
    log=Path(state['experience_path']).with_suffix('.jsonl');events=[]
    for line in log.read_text().splitlines():
        try:e=json.loads(line)
        except ValueError:continue
        if e.get('learning_regime')=='exit-v2-standard-controls-20261023':events.append(e)
    selections=[e for e in events if e.get('kind')=='execution_selection']
    latest_before=max((e for e in selections if e['recorded_utc']<CUT),key=lambda e:e['recorded_utc'],default={})
    first_after=min((e for e in selections if e['recorded_utc']>=CUT),key=lambda e:e['recorded_utc'],default={})
    control_identity=[]
    with sqlite3.connect(worker.storage()/'trade_memory.history.sqlite') as con:
        for recorded,raw in con.execute('SELECT recorded_utc,payload FROM revisions WHERE kind="terminal_state" ORDER BY id'):
            data=json.loads(raw)
            control_identity.append({'recorded_utc':recorded,'local':local(recorded),'state':data})
    closed_after=[r for r in active if r['closed_utc']>=CUT]
    symbols[symbol]={'balance':s['balance'],'equity':s['equity'],'positions':s['positions'],
        'run_id':state['id'],'run_started_local':local(state['started_utc']),
        'reconnected_local':local(state.get('reconnected_utc')),'current_code_revision':state.get('code_revision'),
        'current_learning_regime':state.get('learning_regime'),
        'last_selection_before':latest_before,'first_selection_after':first_after,
        'near_restart_resets':[{'kind':e['kind'],'local':local(e['recorded_utc'])} for e in events
            if CUT-300<=e['recorded_utc']<=CUT+600 and e['kind'] in ('regime_changed','paper_abandoned_on_restart','observation_gap')],
        'terminal_state_revisions':control_identity,'missing_manual_exit_position_ids':missing,
        'before':metrics([r for r in active if r['closed_utc']<CUT]),'after':metrics(closed_after),
        'carried':metrics([r for r in closed_after if r['entry_utc']<CUT]),
        'new_entries':metrics([r for r in closed_after if r['entry_utc']>=CUT]),
        'by_strategy_after':{k:metrics([r for r in closed_after if r['strategy']==k]) for k in {r['strategy'] for r in closed_after}}}

last_context=max((c for c in all_contexts if c.get('recorded_utc',0)<CUT),key=lambda c:c['recorded_utc'])
summary={'checked_local':local(now),'restart_local':local(CUT),'restart_utc':CUT,
    'last_balance_before':{'local':local(last_context['recorded_utc']),'balance':last_context['balance'],'equity':last_context['equity']},
    'current_balance':s['balance'],'current_equity':s['equity'],
    'balance_change_since_last_pre_restart_record':round(s['balance']-last_context['balance'],2),
    'controls':read(ROOT),'controls_revision':revision(read(ROOT)),'current_fingerprint':fingerprint(ROOT),
    'before':metrics([r for r in rows if r['closed_utc']<CUT]),
    'after':metrics([r for r in rows if r['closed_utc']>=CUT]),
    'carried':metrics([r for r in rows if r['closed_utc']>=CUT and r['entry_utc']<CUT]),
    'new_entries':metrics([r for r in rows if r['entry_utc']>=CUT]),'symbols':symbols}
(OUT/'audit.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
(OUT/'trades.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
output=io.StringIO();keys=['symbol','position_id','strategy','entry_local','closed_local','net','risk_cash','reward_r','cohort']
writer=csv.DictWriter(output,fieldnames=keys);writer.writeheader()
for row in rows:writer.writerow({k:row[k] for k in keys})
(OUT/'trades.csv').write_text(output.getvalue())
print(json.dumps({k:v for k,v in summary.items() if k not in ('symbols','controls')},ensure_ascii=False,indent=2))
print(json.dumps({s:{k:d[k] for k in ('before','after','carried','new_entries','near_restart_resets','by_strategy_after')} for s,d in symbols.items()},ensure_ascii=False,indent=2))
