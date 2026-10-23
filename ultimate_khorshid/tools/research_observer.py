"""Observe existing demo workers without restarting them or touching orders.

Own lock/status/research files are the only writes. Broker files and execution
journals are opened read-only. Run via scripts/research_trader.py.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

from ultimate_khorshid.tools.demo_learning import atomic
from ultimate_khorshid.tools.market_learning import ContextModel, describe
from ultimate_khorshid.tools.strategy_research import StrategyLab, ForwardTrial
from ultimate_khorshid.tools.trade_memory import TradeMemory
from ultimate_khorshid.tools.demo_learning import Experience,NAMES
from ultimate_khorshid.tools.demo_lab import indicators
from ultimate_khorshid.tools.news_analysis import analyze as analyze_news,risk_factor
from ultimate_khorshid.tools.portfolio_policy import allocate
from ultimate_khorshid.tools.exit_rules import POLICY_VERSION, outcome_policy
from ultimate_khorshid.tools.headline_research import read as read_headlines, adjustment as news_adjustment, run as headline_loop
from ultimate_khorshid.tools.execution_policy import select as execution_selection

ROOT=Path(__file__).resolve().parents[2]
SYMBOLS=('XAUUSD','EURUSD','USDJPY')


def ensure_started(root=ROOT):
    """One independent observer for all charts; singleton lock resolves races."""
    output=root/'.khorshid-research';output.mkdir(exist_ok=True)
    with (output/'observer.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            return {'status':'already_running'}
        fcntl.flock(lock,fcntl.LOCK_UN)
    with (output/'observer.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,str(root/'scripts/research_trader.py')],
            cwd=root,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    return {'status':'starting','pid':process.pid}


def observe_symbol(root, terminal, symbol, now=None):
    now=time.time() if now is None else now
    path=terminal/'MQL5/Files/khorshid_multi'/symbol/'khorshid_demo_snapshot.json'
    if path.stat().st_size>2_000_000:
        raise ValueError('Snapshot too large')
    snapshot=json.loads(path.read_text(encoding='utf-8-sig'))
    if (snapshot.get('demo') is not True or snapshot.get('connected') is not True
            or snapshot.get('symbol')!=symbol or not -5<=now-snapshot.get('generated_utc',0)<=15):
        raise ValueError('A fresh, connected demo snapshot for this symbol is required')
    state_path=root/'.khorshid-multi'/symbol/'state.json'
    state=json.loads(state_path.read_text())
    if state['login']!=snapshot['login'] or state['period']!=snapshot['period']:
        raise ValueError('Worker/snapshot account or timeframe mismatch')
    # Derive paths from known root and scope, never a path supplied by terminal data.
    scope=f"{snapshot['login']}:{symbol}:{snapshot['period']}"
    key=hashlib.sha256(scope.encode()).hexdigest()[:20]
    journal=TradeMemory.read_only(root/'.khorshid-multi'/symbol/'trade_memory.sqlite')
    groups=journal.outcomes(snapshot)
    legacy_path=root/'.khorshid-multi'/symbol/'experience'/(key+'.json')
    legacy=json.loads(legacy_path.read_text()).get('live_seen',[]) if legacy_path.exists() else []
    groups={ident:outcome for ident,outcome in groups.items() if str(ident) not in legacy and outcome_policy(outcome)==POLICY_VERSION}
    scoped=Experience(legacy_path)
    scoped.set_regime(state.get('learning_regime'))
    if scoped.regime:groups={ident:o for ident,o in groups.items() if o.get('learning_regime')==scoped.regime}
    context_path=scoped.context_path()
    model=ContextModel(context_path,snapshot['login'])
    imported=model.observe(groups,{str(p['identifier']) for p in snapshot['positions']})
    directory=root/'.khorshid-research'/symbol/key/f'policy-{POLICY_VERSION}'
    directory.mkdir(parents=True,exist_ok=True)
    lab=StrategyLab(directory/'lab')
    trial_paths=sorted(directory.glob('forward-*.json'))
    trials=[]
    for trial_path in trial_paths:
        trial_state=json.loads(trial_path.read_text())
        experiment=json.loads((lab.directory/(trial_state['experiment_id']+'.json')).read_text())
        trials.append(ForwardTrial(trial_path).observe(snapshot,experiment,now))
    latest_path=lab.directory/'latest.json'
    latest=json.loads(latest_path.read_text()) if latest_path.exists() else None
    # Historical work is bounded and never runs in the broker heartbeat thread.
    bar=snapshot['bars'][-1]['time']
    should_screen=latest is None or bar-latest['holdout_end']>=snapshot['period_seconds']*24
    if should_screen:
        latest=lab.analyze(snapshot)
        if latest['status']=='ready_for_forward_paper':
            trial=ForwardTrial(directory/('forward-'+latest['experiment_id']+'.json'))
            trials.append(trial.observe(snapshot,latest,now))
    out={'symbol':symbol,'scope':scope,'updated_utc':now,'broker_writes':False,
         'execution_uses_context':bool(state.get('entry_decision',{}).get('market_context')),
         'new_context_results':imported,'context_learning':ContextModel.summary(context_path,snapshot['login']),
         'market_context':describe(snapshot['bars'],snapshot['generated_utc'],snapshot['ask']-snapshot['bid']),
         'latest_experiment':{k:latest[k] for k in ('experiment_id','status','candidate_before_holdout',
             'hypotheses_tested','overlaps_previous_holdout','automatic_deployment')},
         'forward_trials':[{'experiment_id':t['experiment_id'],'status':t['status'],
             'baseline_closed':t['baseline']['closed'],'challenger_closed':t['challenger']['closed'],
             'gaps':t['gaps']} for t in trials]}
    atomic(directory/'status.json',out)
    return out


def read_json(path,limit=2_000_000):
    if path.stat().st_size>limit:
        raise ValueError('Oversized input: '+path.name)
    return json.loads(path.read_text(encoding='utf-8-sig'))


def observe_portfolio(root,terminal,now=None):
    now=time.time() if now is None else now
    snapshots={};candidates={};outcomes={};analyses={};factors={};permissions={}
    headlines=read_headlines(root)
    cache=root/'.khorshid-multi/shared-news/calendar.json'
    try: calendar=read_json(cache)
    except (OSError,ValueError): calendar={}
    try: releases=read_json(terminal/'MQL5/Files/khorshid_multi/shared-news/mt5_calendar.json')
    except (OSError,ValueError): releases={}
    for symbol in SYMBOLS:
        s=read_json(terminal/'MQL5/Files/khorshid_multi'/symbol/'khorshid_demo_snapshot.json')
        from ultimate_khorshid.tools.trading_controls import read as read_controls
        s['trading_controls']=read_controls(root)
        snapshots[symbol]=s
        scope=f"{s['login']}:{symbol}:{s['period']}"
        key=hashlib.sha256(scope.encode()).hexdigest()[:20]
        path=root/'.khorshid-multi'/symbol/'experience'/(key+'.json')
        learner=Experience(path)
        signals,_=indicators(s['bars'])
        context=describe(s['bars'],s['generated_utc'],s['ask']-s['bid'])
        selection=execution_selection(root,s,signals,context,now,learner=learner)
        permissions[symbol]=selection
        chosen=selection['selected']
        direction=signals[chosen][-1] if chosen else 0
        cited=headlines.get('symbols',{}).get(symbol,{}).get('evidence_ids',[])
        candidates[symbol]={'strategy':chosen,'direction':direction,'market_context':context,
            'signal_bar':s['bars'][-1]['time'],'signals':{name:values[-1] for name,values in signals.items()},
            'headline_adjustment':0,'headline_has_article':False}
        groups=TradeMemory.read_only(root/'.khorshid-multi'/symbol/'trade_memory.sqlite').outcomes(s)
        outcomes[symbol]={ident:g for ident,g in groups.items() if str(ident) not in learner.data['live_seen']}
        if selection.get('learning_regime'):
            outcomes[symbol]={ident:g for ident,g in outcomes[symbol].items()
                              if g.get('learning_regime')==selection['learning_regime']}
        analyses[symbol]=analyze_news(symbol,s,calendar,releases,now)
        analyses[symbol]['execution_effects_enabled']=False
        analyses[symbol]['headline_research']={'status':headlines.get('status','unavailable'),
            'analysis':headlines.get('symbols',{}).get(symbol,{})}
        factors[symbol]=1. if (not s['trading_controls']['news_entry_block_enabled'] or analyses[symbol]['schedule']['allow_entry']) else 0.
    advice=allocate(snapshots,candidates,outcomes,factors,now,news_analyses=analyses)
    advice['news_analysis']=analyses
    advice['execution_policy']=permissions
    advice['news_mode']='report_only'
    if not any(p['allowed'] for p in permissions.values()):
        advice.update(status='research_only',execution_ready=False,
            reason='No reviewed frozen strategy is approved for execution')
    return advice


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--status',action='store_true')
    parser.add_argument('--stop',action='store_true',help='Stop only the research observer, not trading workers')
    args=parser.parse_args(argv)
    output=ROOT/'.khorshid-research';output.mkdir(exist_ok=True)
    status_path=output/'status.json'
    if args.status:
        print(status_path.read_text() if status_path.exists() else '{"status":"not_started"}')
        return 0
    if args.stop:
        state=json.loads(status_path.read_text()) if status_path.exists() else {}
        pid=state.get('pid')
        if type(pid) is not int or state.get('status')!='observing':
            print('No active research observer recorded.')
            return 0
        try:
            command=Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')
            if str(ROOT/'scripts/research_trader.py').encode() not in command:
                raise ValueError('Observer process identity mismatch; no signal sent')
            os.kill(pid,signal.SIGTERM)
        except ProcessLookupError:
            print('Research observer has already exited.')
            return 0
        print('Research observer stop requested; trading workers unchanged.')
        return 0
    terminal=Path(os.environ.get('KHORSHID_MT5_DATA_DIR',str(Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5'))).expanduser()
    stopped=threading.Event()
    signal.signal(signal.SIGTERM,lambda *_:stopped.set())
    signal.signal(signal.SIGINT,lambda *_:stopped.set())
    with (output/'observer.lock').open('a') as lock:
        try:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print('Research observer is already running.')
            return 1
        threading.Thread(target=headline_loop,args=(ROOT,stopped),daemon=True).start()
        while not stopped.is_set():
            results={}
            for symbol in SYMBOLS:
                try:
                    results[symbol]=observe_symbol(ROOT,terminal,symbol)
                except (ValueError,OSError,KeyError,IndexError) as exc:
                    results[symbol]={'status':'waiting_for_data','error':str(exc),'broker_writes':False}
                except Exception as exc:
                    # Research failure must never stop the existing trading workers.
                    results[symbol]={'status':'research_error','error':type(exc).__name__+': '+str(exc),'broker_writes':False}
            try:
                portfolio=observe_portfolio(ROOT,terminal)
            except Exception as exc:
                portfolio={'version':1,'updated_utc':time.time(),'expires_utc':time.time(),
                    'status':'allocation_unavailable','execution_ready':False,'symbols':{},
                    'reason':type(exc).__name__+': '+str(exc)}
            atomic(output/'portfolio.json',portfolio)
            for symbol,result in results.items():
                result['portfolio_advice']=portfolio.get('symbols',{}).get(symbol,{})
                result['portfolio_status']=portfolio['status']
                result['news_analysis']=portfolio.get('news_analysis',{}).get(symbol,{})
            atomic(status_path,{'status':'observing','pid':os.getpid(),'updated_utc':time.time(),
                               'symbols':results,'portfolio':portfolio,'automatic_deployment':False})
            if args.once:
                print(status_path.read_text())
                return 0
            stopped.wait(5)
        atomic(status_path,{'status':'stopped','pid':os.getpid(),'updated_utc':time.time(),'automatic_deployment':False})
    return 0
