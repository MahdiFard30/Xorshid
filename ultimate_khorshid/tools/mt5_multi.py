"""Three-symbol DEMO controller. No orders are sent by installation."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import time
from ultimate_khorshid.tools import mt5_multi_worker as worker

SYMBOLS=worker.SYMBOLS

def select(symbol):
    worker.SYMBOL=symbol
    os.environ['KHORSHID_DEMO_SYMBOL']=symbol

def compact(r):
    keys=('symbol','status','runner_alive','fresh_snapshot','error','last_reason',
          'max_positions','entry_risk_pct','symbol_risk_cap_pct','selected','robot_open_positions','robot_realized_net','execution_ack','execution_policy','research','summary',
          'trading_controls','trading_controls_revision','native_controls','controls_match','experiment_id','profit_exit_mode')
    return {k:r[k] for k in keys if k in r}

def reports(full=False):
    result={}
    for symbol in SYMBOLS:
        select(symbol)
        try:
            r=worker.report()
            # never_started should still expose the terminal setup state.
            if r.get('status')=='never_started':
                try:
                    s=worker.snapshot()
                    r.update(symbol=symbol,runner_alive=worker.running(),fresh_snapshot=True,
                             robot_open_positions=s['own_positions'],algo_enabled=s['algo_enabled'])
                except (ValueError,OSError) as exc: r.update(error=str(exc),fresh_snapshot=False)
            result[symbol]=r if full else compact(r)
        except Exception as exc: result[symbol]={'error':str(exc)}
    return result

def old_runner_active():
    path=worker.ROOT/'.khorshid-demo'/'runner.lock'
    if not path.exists(): return False
    with path.open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return True
        fcntl.flock(lock,fcntl.LOCK_UN)
    return False

def preflight():
    from ultimate_khorshid.tools.execution_policy import load
    if load(worker.ROOT).get('enabled') is not True:
        raise ValueError('ارسال سفارش برای ممیزی غیرفعال است؛ ابتدا اعتبارسنجی مستقل و بازبینی لازم است.')
    if old_runner_active(): raise ValueError('Stop the old mt5_demo runner first.')
    select(SYMBOLS[0])
    legacy=worker.files().parent.parent/'khorshid_demo_snapshot.json'
    if legacy.exists() and -5<=time.time()-legacy.stat().st_mtime<=15:
        raise ValueError('Remove the old KhorshidDemoTrader from its chart first.')
    snapshots={}
    for symbol in SYMBOLS:
        select(symbol)
        s=worker.snapshot()
        worker.execution_guard(worker.ROOT,s)
        if s.get('executor_version')!=9 or s.get('exit_policy_version')!=worker.POLICY_VERSION:
            raise ValueError(symbol+': نسخهٔ اکسپرت و کارگر هماهنگ نیست؛ اکسپرت ۳٫۵۰ لازم است')
        if not s['algo_enabled'] or s['halted']:
            raise ValueError(symbol+': Algo Trading disabled or risk limit reached')
        if s['blocking_positions'] or s['total_orders']:
            raise ValueError(symbol+': manual/other robot exposure or pending orders block start')
        if s['own_positions'] and not worker.running():
            raise ValueError(symbol+': existing robot position; use stop and confirm closure first')
        if len(s['bars'])<1000: raise ValueError(symbol+': load at least 1000 closed candles (Home key)')
        snapshots[symbol]=s
    if len({s['login'] for s in snapshots.values()})!=1:
        raise ValueError('All three charts must use the same demo account')
    return snapshots

def stop_all():
    # Publish every stop marker BEFORE waiting on any worker.
    for symbol in SYMBOLS:
        select(symbol)
        worker.atomic(worker.files()/'khorshid_demo_stop.flag','User requested portfolio stop\n')
    deadline=time.monotonic()+10
    while time.monotonic()<deadline:
        alive=False
        for symbol in SYMBOLS:
            select(symbol); alive |= worker.running()
        if not alive: break
        time.sleep(.2)
    out=reports()
    confirmed=all(r.get('fresh_snapshot') and r.get('robot_open_positions')==0 and not r.get('runner_alive',True) for r in out.values())
    return {'stop_confirmed':confirmed,'symbols':out,
            'summary':('Stopped; no open robot positions confirmed.' if confirmed else
                       'Stop requested. Keep MT5 and Algo Trading on until closure is confirmed.')}

def start_all():
    preflight() # Validate all three BEFORE starting any worker.
    result={}
    try:
        for symbol in SYMBOLS:
            select(symbol); result[symbol]=worker.start()
    except Exception as exc:
        stopped=stop_all()
        return {'error':str(exc),'summary':'Partial start failed; stop requested for all three.', 'stop':stopped}
    return {'symbols':result,'summary':'Three demo workers enabled. Entries require fresh quotes and valid signals.'}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('start','stop','status','report'))
    args=parser.parse_args()
    root=worker.ROOT/'.khorshid-multi'; root.mkdir(exist_ok=True)
    with (root/'controller.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            if args.action=='start': out=start_all()
            elif args.action=='stop': out=stop_all()
            else: out={'symbols':reports(full=args.action=='report')}
        except (ValueError,OSError,KeyError) as exc: out={'error':str(exc)}
    print(json.dumps(out,ensure_ascii=False,indent=2))
    return 1 if out.get('error') else 0
if __name__=='__main__': raise SystemExit(main())
