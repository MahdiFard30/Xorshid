"""Demo-only trainer and deterministic MT5 execution service. CLI and agent tool."""
from concurrent.futures import ThreadPoolExecutor
from ultimate_khorshid.tools.mt5_entry_policy import decision, weekly_gate, first_positive_exit
from ultimate_khorshid.tools.mt5_news_calendar import Calendar, gate
from ultimate_khorshid.tools.mt5_recovery import Recovery, lease_text
from ultimate_khorshid.tools.trade_memory import TradeMemory
import argparse
import csv
import hashlib
import fcntl
import io
import json
import math
import os
from pathlib import Path
import re
import signal
import sqlite3
import subprocess
import sys
import time
import uuid
from ultimate_khorshid.core.registry import ToolRegistry
from ultimate_khorshid.core.types import ToolResult
from ultimate_khorshid.tools.base import BaseTool, ToolSpec
from ultimate_khorshid.tools.demo_lab import CATALOG, RULES, VERSION, evaluate, indicators
from ultimate_khorshid.tools.portfolio_policy import constrain as portfolio_gate
from ultimate_khorshid.tools.managed_exits import entry_profile, STOP_ATR, SIZING_SCALE, QUICK_TARGET_R, STAGED_TARGET_R
from ultimate_khorshid.tools.exit_rules import POLICY_VERSION
from ultimate_khorshid.tools.entry_protections import constrain as protect_entry
from ultimate_khorshid.tools.execution_policy import select as execution_selection, constrain as execution_gate, require as execution_guard

ROOT=Path(__file__).resolve().parents[2]
SYMBOL=os.environ.get('KHORSHID_DEMO_SYMBOL','')
SYMBOLS=('XAUUSD','EURUSD','USDJPY')
def channel():
    if SYMBOL not in SYMBOLS: raise ValueError('Set KHORSHID_DEMO_SYMBOL to a supported symbol')
    return SYMBOL

def storage():
    p=ROOT/'.khorshid-multi'/channel(); p.mkdir(parents=True,exist_ok=True); return p

def files():
    return Path(os.environ.get('KHORSHID_MT5_DATA_DIR',str(Path.home()/'.mt5/drive_c/Program Files/MetaTrader 5'))).expanduser()/'MQL5/Files'/'khorshid_multi'/channel()

def atomic(path,text):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp'); path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with tmp.open('w',encoding='utf-8') as f: f.write(text); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally: tmp.unlink(missing_ok=True)

def put(path,data): atomic(path,json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))

def db():
    con=sqlite3.connect(storage()/'journal.sqlite',timeout=10)
    con.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, data TEXT)')
    con.execute('CREATE TABLE IF NOT EXISTS deals (login INTEGER, ticket INTEGER, run_id TEXT, data TEXT, PRIMARY KEY(login,ticket))')
    return con

def save_run(run):
    with db() as con: con.execute('INSERT OR REPLACE INTO runs VALUES (?,?)',(run['id'],json.dumps(run,ensure_ascii=False)))
    put(storage()/'state.json',run)

def state():
    try: return json.loads((storage()/'state.json').read_text())
    except FileNotFoundError: return {}

class SnapshotUnavailable(ValueError):
    """Transient terminal outage: pause without stopping the worker."""


def snapshot():
    path=files()/'khorshid_demo_snapshot.json'
    try:
        with path.open(encoding='utf-8-sig') as f:
            stat=os.fstat(f.fileno())
            if stat.st_size>2_000_000 or not -5<=time.time()-stat.st_mtime<=15: raise SnapshotUnavailable('داده قدیمی است؛ KhorshidMultiTrader را روی چارت فعال نگه دار.')
            s=json.loads(f.read(2_000_001))
    except (OSError,json.JSONDecodeError):
        raise SnapshotUnavailable('دادهٔ متاتریدر موقتاً در دسترس نیست؛ منتظر اتصال یا بارگذاری چارت.') from None
    if s.get('executor_version') not in (5,6,7,8,9): raise ValueError('اکسپرت سازگار KhorshidMultiTrader را کامپایل و روی چارت فعال کن.')
    if s['executor_version']>=6:
        instance=s.get('executor_instance')
        if not isinstance(instance,str) or not instance or len(instance)>128 or any(c in instance for c in '\t\r\n'):
            raise ValueError('Invalid executor restart identity')
    if s.get('symbol')!=channel(): raise ValueError('Wrong symbol channel')
    if s.get('schema')!=2 or s.get('demo') is not True: raise ValueError('فقط حساب DEMO پذیرفته می‌شود.')
    if not -5<=time.time()-s.get('generated_utc',0)<=15: raise SnapshotUnavailable('زمان داده نامعتبر است.')
    if s.get('connected') is not True: raise SnapshotUnavailable('متاتریدر به کارگزار وصل نیست.')
    if not isinstance(s.get('bars'),list) or len(s['bars'])<1000:
        raise SnapshotUnavailable('تاریخچهٔ چارت پس از راه‌اندازی هنوز آماده نیست؛ منتظر بارگذاری حداقل ۱۰۰۰ کندل.')
    for k in ('balance','equity','point','bid','ask','tick_age_seconds','bar_age_seconds','entry_window_seconds','max_positions'):
        if not isinstance(s.get(k),(int,float)) or not math.isfinite(s[k]): raise ValueError('Invalid snapshot '+k)
    if s['max_positions'] not in (1,2) or not 0 < s['entry_window_seconds'] <= 300:
        raise ValueError('Invalid executor entry limits')
    from ultimate_khorshid.tools.trading_controls import read as read_controls
    s['trading_controls']=read_controls(ROOT)
    return s

def running():
    with (storage()/'runner.lock').open('a') as f:
        try: fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB); fcntl.flock(f,fcntl.LOCK_UN); return False
        except BlockingIOError: return True

def same_account(run,s):
    if s['login']!=run['login'] or s['symbol']!=run['symbol'] or s['period']!=run['period']:
        raise ValueError('Account, chart symbol or timeframe changed. Stop and start explicitly.')

def ingest(run,s):
    same_account(run,s)
    run['native_controls']={k:s.get(k) for k in ('ea_version','controls_revision','cooldown_bars','stop_cluster_enabled')}
    with db() as con:
        for d in s.get('deals',[]):
            if d['ticket'] not in run['baseline_deals']:
                con.execute('INSERT OR IGNORE INTO deals VALUES (?,?,?,?)',(s['login'],d['ticket'],run['id'],json.dumps(d)))
    run.update(balance=s['balance'],equity=s['equity'],own_positions=s['own_positions'],last_snapshot_utc=s['generated_utc'],terminal_note=s.get('note',''),max_positions=s['max_positions'],risk_policy_version=s.get('risk_policy_version'),executor_version=s.get('executor_version'),exit_policy_version=s.get('exit_policy_version'))

def report(refresh=True):
    run=state()
    if not run: return {'status':'never_started','summary':'هنوز دورهٔ تمرین شروع نشده است.'}
    fresh=False; error=''
    if refresh:
        try:
            s=snapshot(); ingest(run,s); fresh=True
            if run.get('status') in ('stopping','stop_pending') and s['own_positions']==0:
                run['status']='stopped'; run['ended_utc']=time.time()
            # Runner owns the current state; a reader must not overwrite it while active.
            if not running(): save_run(run)
        except (ValueError,OSError) as exc: error=str(exc)
    with db() as con: rows=con.execute('SELECT data FROM deals WHERE run_id=?',(run['id'],)).fetchall()
    deals=[json.loads(r[0]) for r in rows]; groups={}
    for d in deals:
        g=groups.setdefault(str(d['position_id']),{'net':0.,'has_exit':False,'strategy':'unknown'})
        g['net']+=d['net']; g['has_exit'] |= d['entry'] in (1,3)
        if d.get('comment','').startswith('KH:'): g['strategy']=d['comment'][3:]
    # Partial closures are explicitly reported as positions with exit deals, not necessarily fully closed trades.
    exited=[g for g in groups.values() if g['has_exit']]
    net=round(sum(d['net'] for d in deals),2)
    by_strategy={}
    for g in groups.values(): by_strategy[g['strategy']]=round(by_strategy.get(g['strategy'],0)+g['net'],2)
    result={'news_filter':run.get('news_filter',{}),'entry_decision':run.get('entry_decision',{}),'run_id':run['id'],'status':run.get('status'),'runner_alive':running(),'fresh_snapshot':fresh,'error':error,
        'symbol':run['symbol'],'period':run['period'],'currency':run['currency'],
        'start_balance':run['start_balance'],'latest_balance':run.get('balance'),'latest_equity':run.get('equity'),
        'account_balance_change':round(run.get('balance',run['start_balance'])-run['start_balance'],2),
        'robot_realized_net':net,'positions_with_exit_deals':len(exited),'winning_positions_with_exits':sum(g['net']>0 for g in exited),
        'losing_positions_with_exits':sum(g['net']<0 for g in exited),'robot_open_positions':run.get('own_positions'),
        'net_by_strategy':by_strategy,'selected':run.get('selected'),'last_reason':run.get('reason'),
        'experiment_id':run.get('experiment_id'),'profit_exit_mode':run.get('profit_exit_mode'),
        'started_utc':run['started_utc'],'last_snapshot_utc':run.get('last_snapshot_utc'),
        'execution_ack':run.get('last_ack'),'max_positions':run.get('max_positions'),'entry_risk_pct':(0.25 if run.get('executor_version') in (8,9) else 0.5 if run.get('risk_policy_version')==2 else 0.025),'symbol_risk_cap_pct':(0.5 if run.get('risk_policy_version')==2 else 0.05),'configured_entry_risk_pct':0.25,'configured_stop_atr':STOP_ATR,'configured_exit_policy_version':POLICY_VERSION,'configured_portfolio_risk_cap_pct':0.5,'risk_upgrade_active':run.get('risk_policy_version')==2, 'note':'Robot net includes reported deal profit/commission/swap/fee. Account change can include external operations. Partial exits may still leave exposure; estimated floating P/L is in equity.'}
    from ultimate_khorshid.tools.execution_policy import authorize
    from ultimate_khorshid.tools.trading_controls import read as read_controls,revision
    result['trading_controls']=read_controls(ROOT)
    result['trading_controls_revision']=revision(result['trading_controls'])
    result['native_controls']=run.get('native_controls',{})
    result['controls_match']=result['native_controls'].get('controls_revision')==result['trading_controls_revision']
    result['execution_policy']=authorize(ROOT,{'login':run['login'],'symbol':run['symbol'],'period':run['period'],'demo':True})
    if result['execution_policy'].get('entry_cap_fraction') is not None:
        result['native_entry_risk_cap_pct']=result['entry_risk_pct']
        result['entry_risk_pct']=result['configured_entry_risk_pct']=100*result['execution_policy']['entry_cap_fraction']
    try:
        latest=sorted((storage()/'evaluations'/run['id']).glob('*.json'))
        if latest:
            screen=json.loads(latest[-1].read_text())
            result['strategy_tests']={k:{'validation':v['validation'],'holdout':v['holdout'],'stress':v['stress']} for k,v in screen['results'].items()}
            result['evaluation_path']=str(latest[-1])
    except (OSError,ValueError,KeyError): pass
    if run.get('experience_path'):
        from ultimate_khorshid.tools.demo_learning import Experience
        try:
            experience=Experience(run['experience_path'])
            if run.get('learning_regime'):experience.set_regime(run['learning_regime'])
            result['learning']=experience.summary()
        except (OSError,ValueError,KeyError) as exc: result['learning_error']=str(exc)
    research_path=ROOT/'.khorshid-research'/'status.json'
    if research_path.exists():
        try:
            research=json.loads(research_path.read_text())
            observed=research.get('symbols',{}).get(run['symbol'],{})
            expected=f"{run['login']}:{run['symbol']}:{run['period']}"
            if observed.get('scope')==expected:
                result['research']={**observed,'observer_status':research['status'],
                    'fresh_observation':-5<=time.time()-observed.get('updated_utc',0)<=30}
        except (OSError,ValueError,KeyError):
            result['research_error']='Research status unavailable; trading report remains separate.'
    if (storage()/'trade_memory.sqlite').exists() and fresh:
        result['trade_memory']=TradeMemory(storage()/'trade_memory.sqlite').summary(s)
    result['summary']=(f"وضعیت: {result['status']}. موجودی شروع {result['start_balance']:,.2f} و آخرین موجودی {result['latest_balance']:,.2f} {run['currency']}. "
       f"سود یا زیان ثبت‌شدهٔ ربات {net:+,.2f}. تعداد پوزیشن دارای خروج {len(exited)}؛ سودده {result['winning_positions_with_exits']} و زیان‌ده {result['losing_positions_with_exits']}. "
       f"پوزیشن باز ربات: {run.get('own_positions','نامشخص')}. استراتژی: {run.get('selected') or 'منتظر سیگنال ورود'}. "+
       ("" if fresh else "دادهٔ زنده در دسترس نیست؛ این آخرین گزارش ثبت‌شده است. "))
    if not result['execution_policy']['allowed']:
        result['summary']='ارسال سفارش تازه تا پایان اعتبارسنجی و بازبینی غیرفعال است. '+result['summary']
    if 'learning' in result:
        result['summary']+=f" تمرین شبیه‌سازی‌شدهٔ بسته‌شده: {result['learning']['paper_closed']}. معاملات دمو واردشده در یادگیری: {result['learning']['demo_closed_learned']}."
        result['summary']+=f" نتایج قدیمی با ریسک تقریبی، محفوظ و جدا از امتیاز جدید: {result['learning'].get('legacy_demo_closed_approximate',0)}."
        context=result['learning'].get('context_learning',{})
        result['summary']+=f" نتایج تأییدشده با زمینهٔ ورود: {context.get('verified_context_results',0)}."
    if 'research' in result:
        result['summary']+=' پژوهش استراتژی‌ها جدا و بدون ارسال سفارش اجرا می‌شود.'
        if not result['research'].get('execution_uses_context'):
            result['summary']+=' استفادهٔ اجرای معاملات از انتخاب زمینه‌ای، نیازمند بارگذاری نسخهٔ جدید کارگر است.'
    folder=storage()/'reports'; folder.mkdir(exist_ok=True)
    put(folder/(run['id']+'.json'),result)
    output=io.StringIO(); w=csv.DictWriter(output,fieldnames=['ticket','position_id','entry','time','net','comment']); w.writeheader()
    for d in deals: w.writerow({k:d.get(k,'') for k in w.fieldnames})
    atomic(folder/(run['id']+'.csv'),output.getvalue())
    result['report_path']=str(folder/(run['id']+'.json')); result['deals_csv']=str(folder/(run['id']+'.csv'))
    return result

def stop(wait=8):
    atomic(files()/'khorshid_demo_stop.flag','User requested stop\n')
    # Marker dominates requests in EA, including one already queued.
    deadline=time.monotonic()+wait
    while running() and time.monotonic()<deadline: time.sleep(.2)
    result=report()
    if result.get('robot_open_positions',0)>0 or not result.get('fresh_snapshot',False):
        result['summary']='ورود جدید متوقف شد؛ بسته‌شدن پوزیشن‌ها هنوز تأیید نشده. متاتریدر، اتصال و Algo Trading را فعال نگه دار. '+result['summary']
    return result

def start():
    with (storage()/'start.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if running(): return report()
        s=snapshot()
        permission=execution_guard(ROOT,s)
        if s.get('executor_version')!=9 or s.get('exit_policy_version')!=POLICY_VERSION:
            raise ValueError('نسخهٔ کارگر و اکسپرت هماهنگ نیست؛ اکسپرت ۳٫۵۰ باید نصب و روی چارت بارگذاری شود.')
        if not s['algo_enabled']: raise ValueError('Algo Trading و Allow Algo Trading در تنظیمات EA باید فعال باشند.')
        if s['halted']: raise ValueError('Risk limit reached; trainer cannot override it.')
        if s['own_positions'] or s['blocking_positions'] or s['total_orders']: raise ValueError('Start requires no open positions or pending orders in this demo account.')
        if len(s['bars'])<1000: raise ValueError('حداقل ۱۰۰۰ کندل لازم است؛ در چارت کلید Home را بزن و صبر کن تاریخچه بارگیری شود.')
        (files()/'khorshid_demo_stop.flag').unlink(missing_ok=True)
        (files()/'khorshid_demo_request.tsv').unlink(missing_ok=True)
        log=(storage()/'runner.log').open('a')
        try: proc=subprocess.Popen([sys.executable,'-m','ultimate_khorshid.tools.mt5_multi_worker','run'],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
        finally: log.close()
        for _ in range(25):
            if running(): return {'status':'starting','pid':proc.pid,'execution_policy':permission,
                'summary':'کارگر دمو شروع شد؛ اجرای سفارش هنوز تأیید نشده است. استراتژی ثابت و مجوز زمان‌دار اجرا بررسی می‌شود.'}
            if proc.poll() is not None: raise ValueError('Runner stopped; inspect '+str(storage()/'runner.log'))
            time.sleep(.1)
        raise ValueError('Runner startup not confirmed; inspect runner.log')

def send(run,s,action,direction=0,atr=0,strategy='none',tickets=()):
    ident=time.time_ns()//1000 # exact double below 2**53
    distance,target=0.,0.
    extra=[]
    if action=='open':
        execution_guard(ROOT,s,strategy)
        from ultimate_khorshid.tools.portfolio_policy import ENTRY_CAP,SYMBOL_CAP,finite
        plan=run.get('entry_decision',{}).get('plan',{})
        verified=execution_gate(plan,ROOT,s,time.time(),advice={'news_mode':run.get('entry_decision',{}).get('news_mode')})
        if verified.get('action')!='open':
            raise ValueError(verified.get('reason','Unreviewed execution plan'))
        plan=verified
        fraction,cap=plan.get('risk_fraction'),plan.get('symbol_cap_fraction')
        if (s.get('executor_version')!=9 or s.get('exit_policy_version')!=POLICY_VERSION or plan.get('exit_policy_version')!=POLICY_VERSION
                or not finite(fraction) or not 0<fraction<=ENTRY_CAP*SIZING_SCALE
                or not finite(cap) or not fraction<=cap<=SYMBOL_CAP):
            raise ValueError('Missing or invalid bounded risk allocation; order not published')
        profile=plan.get('exit_profile'); expiry=plan.get('thesis_expires_utc')
        expected_target=STAGED_TARGET_R if profile=='staged' else QUICK_TARGET_R
        if (profile not in ('quick','staged') or plan.get('stop_atr')!=STOP_ATR
                or plan.get('target_r')!=expected_target or not finite(atr) or atr<=0
                or not finite(expiry) or (profile=='quick' and expiry!=0)
                or (profile=='staged' and not time.time()+60<=expiry<=time.time()+1800)):
            raise ValueError('Invalid or expired managed exit profile; order not published')
        distance=STOP_ATR*atr; target=expected_target*distance
        extra=[fraction,cap,1 if profile=='staged' else 0,int(expiry)]
    fields=[ident,int(time.time())+15,s['login'],run['id'],action,s['symbol'],direction,distance,target,s['bars'][-1]['time'],strategy,','.join(str(int(t)) for t in tickets),*extra]
    if any('\t' in str(x) or '\n' in str(x) for x in fields): raise ValueError('Invalid request field')
    TradeMemory(storage()/'trade_memory.sqlite').record_intent(run,s,ident,action,direction,distance,target,strategy,tickets)
    atomic(files()/'khorshid_demo_request.tsv','\t'.join(map(str,fields))+'\n')
    run['last_request']=ident

def save_screen(run,s):
    ev=evaluate(s['bars'],s['point']); run['selected']=ev['selected']; run['reason']=ev['reason']; run['screen_bar']=s['bars'][-1]['time']
    folder=storage()/'evaluations'/run['id']; folder.mkdir(parents=True,exist_ok=True)
    put(folder/(str(run['screen_bar'])+'.json'),ev)
    # Keep both failures and successes so failed experiments are not forgotten.
    put(storage()/'latest_evaluation.json',ev)
    put(storage()/'qualified_strategies.json',{'updated_utc':time.time(),'symbol':s['symbol'],'period':s['period'],
        'screening_only':True,'candidates':{k:v for k,v in ev['results'].items() if v['profitable_holdout']},'selected':ev['selected']})
    put(storage()/'catalog.json',{'version':VERSION,'rules':RULES,'strategies':[{'id':i,'name':n,'source':u} for i,n,u in CATALOG]})
    return ev

def resumed_state(s):
    """Resume only an existing fresh session during a supervised process handover."""
    run=state();same_account(run,s)
    lease=(files()/'khorshid_demo_lease.tsv').read_text().strip().split('\t')
    if (run.get('ended_utc') or (files()/'khorshid_demo_stop.flag').exists()
            or len(lease)<6 or lease[1]!=str(s['login'])
            or lease[2]!=run['id'] or lease[3]!=s['symbol'] or lease[4]!=str(s['period'])
            or lease[5]!=s.get('executor_instance') or not 0<=time.time()-int(lease[0])<=10):
        raise ValueError('Fresh matching session required for supervised handover')
    from ultimate_khorshid.tools.execution_policy import authorize
    if not authorize(ROOT,s)['allowed']:raise ValueError('Handover execution policy denied')
    run['resumed_utc']=time.time()
    return run


def run_loop(resume=False):
    with (storage()/'runner.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        def signal_stop(*_): atomic(files()/'khorshid_demo_stop.flag','Process signal stop\n')
        signal.signal(signal.SIGTERM,signal_stop); signal.signal(signal.SIGINT,signal_stop)
        s=snapshot(); run={'id':uuid.uuid4().hex,'login':s['login'],'symbol':s['symbol'],'period':s['period'],'currency':s['currency'],
            'started_utc':time.time(),'start_balance':s['balance'],'baseline_deals':[d['ticket'] for d in s['deals']],
            'balance':s['balance'],'equity':s['equity'],'own_positions':0,'status':'screening','selected':None}
        if resume:run=resumed_state(s)
        from ultimate_khorshid.tools.execution_policy import authorize
        permission=authorize(ROOT,s)
        run['profit_exit_mode']=permission.get('profit_exit_mode','standard')
        run['experiment_id']=permission.get('experiment_id')
        run['learning_regime']=permission.get('learning_regime')
        run['code_revision']=permission.get('code_revision')
        from ultimate_khorshid.tools.demo_learning import Experience
        key=hashlib.sha256(f"{s['login']}:{s['symbol']}:{s['period']}".encode()).hexdigest()[:20]
        run['experience_path']=str(storage()/'experience'/(key+'.json'))
        learner=Experience(run['experience_path'])
        if run.get('learning_regime'):learner.set_regime(run['learning_regime'])
        if run.get('learning_regime')!=learner.data.get('active_learning_regime'):
            learner.event({'kind':'regime_changed','previous':learner.data.get('active_learning_regime'),
                           'current':run.get('learning_regime'),'reason':'Separate scoring; prior records retained'})
            learner.data['active_learning_regime']=run.get('learning_regime')
            learner.activate(s)
        elif not resume:learner.activate(s)
        memory=TradeMemory(storage()/'trade_memory.sqlite')
        screen_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='demo-screen')
        screen_job=None
        calendar=Calendar()
        recovery=Recovery(s)
        # Research owns a separate process; it cannot delay the execution lease.
        try:
            from ultimate_khorshid.tools.research_observer import ensure_started
            ensure_started(ROOT)
        except OSError as exc:
            print('Independent research observer unavailable: '+str(exc),flush=True)
        save_run(run); last_bar=None; bars_since_screen=24; stopping_since=None; failures=0
        allocation_retry_bar=None; allocation_retry_at=0.
        try:
            while True:
                try:
                    s=snapshot(); same_account(run,s); ingest(run,s); failures=0
                    memory.observe(s)
                    try:
                        memory.record_ack(s['login'],json.loads((files()/'khorshid_demo_ack.json').read_text()))
                    except (FileNotFoundError,json.JSONDecodeError): pass
                    groups=memory.outcomes(s)
                    learner.learn_live(groups,None,{str(p['identifier']) for p in s['positions']})
                    if recovery.observe(s):
                        print('Connection recovered; account verified; reconciling positions.', flush=True)
                        run['reconnected_utc']=time.time()
                        run['connection_wait_since']=None
                        # Never replay an old entry or a request with uncertain execution.
                        (files()/'khorshid_demo_request.tsv').unlink(missing_ok=True)
                        run.pop('last_request',None)
                        if s['own_positions']==0:
                            last_bar=s['bars'][-1]['time']
                            run['selected']=None
                            run['status']='waiting_for_next_bar'
                            run['reason']='Connection restored; wait for a new closed candle'
                        else:
                            last_bar=None
                            run['status']='managing_demo_position'
                            run['reason']='Connection restored; existing positions reconciled'
                    if s['halted']: signal_stop(); run['reason']='Risk limit reached'
                    stopping=(files()/'khorshid_demo_stop.flag').exists()
                    if stopping:
                        run['status']='stopping'; stopping_since=stopping_since or time.monotonic()
                        if s['own_positions']==0:
                            run['status']='stopped'; break
                        if time.monotonic()-stopping_since>15:
                            run['status']='stop_pending'; break
                    else:
                        atomic(files()/'khorshid_demo_lease.tsv',lease_text(s,run['id'],time.time()))
                        bar=s['bars'][-1]['time']
                        fast_handling=False
                        pending=run.get('profit_exit_pending')
                        if pending:
                            live={p['ticket'] for p in s['positions']}
                            if not live.intersection(pending['tickets']):
                                run.pop('profit_exit_pending',None)
                            else:
                                fast_handling=True
                                ack_path=files()/'khorshid_demo_ack.json'
                                try:close_ack=json.loads(ack_path.read_text())
                                except (OSError,ValueError):close_ack={}
                                if (close_ack.get('id')==pending['request'] and close_ack.get('status') in ('rejected','pending')
                                        and time.time()-pending['utc']>=5):
                                    run.pop('profit_exit_pending',None)
                                    fast_handling=False
                        fast=first_positive_exit(s) if run.get('profit_exit_mode')=='first_positive_estimated_net' and not fast_handling else None
                        if fast:
                            run['entry_decision']={'utc':time.time(),'selected':None,'plan':fast,
                                'news_mode':'report_only','exit_trigger':'first_positive_estimated_net'}
                            learner.event({'kind':'profit_exit_decision',**run['entry_decision']})
                            memory.record_decision(run,s)
                            send(run,s,'close_tickets',tickets=fast['tickets'])
                            run['profit_exit_pending']={'request':run['last_request'],'tickets':fast['tickets'],'utc':time.time()}
                            run['status']='profit_exit_requested';run['reason']=fast['reason'];fast_handling=True
                        retry=(allocation_retry_bar==bar and time.monotonic()>=allocation_retry_at
                               and 0<=s['bar_age_seconds']<=s['entry_window_seconds'])
                        if not fast_handling and (bar!=last_bar or retry):
                            if bar!=last_bar: bars_since_screen+=1
                            last_bar=bar
                            signals,atr=indicators(s['bars'])
                            learner.advance(s['bars'],signals,atr,s['point'])
                            from ultimate_khorshid.tools.market_learning import describe
                            market_context=describe(s['bars'],s['generated_utc'],s['ask']-s['bid'])
                            from ultimate_khorshid.tools.headline_research import read as read_headlines
                            headlines=read_headlines(ROOT)
                            selection=execution_selection(ROOT,s,signals,context=market_context,now=time.time(),learner=learner)
                            learner.data['decisions']=(learner.data['decisions']+[selection])[-30:]
                            learner.event({'kind':'execution_selection',**selection});learner.save()
                            chosen=selection['selected']; run['selected']=chosen
                            plan=decision(s,signals,atr[-1],chosen)
                            if not selection['allowed'] and plan.get('action')!='close_tickets':
                                plan={'status':'research_only','reason':selection['reason']}
                            elif (selection.get('score_rejected') and chosen is None
                                    and plan.get('status')=='waiting_for_entry_signal'):
                                plan={'status':'waiting_for_nonnegative_strategy_score','reason':selection['reason']}
                            elif selection.get('waiting_for_trend') and plan.get('status')=='waiting_for_entry_signal':
                                plan={'status':'waiting_for_trend_confirmation','reason':selection['reason']}
                            plan=protect_entry(plan,s,groups)
                            if (chosen is None and learner.data['decisions'][-1].get('context_paused')
                                    and plan.get('status')=='waiting_for_entry_signal'):
                                plan={'status':'context_evidence_pause',
                                      'reason':'Current signals paused by persistent negative entry-context evidence'}
                            plan=recovery.constrain(plan,bar)
                            plan=weekly_gate(plan,s)
                            run['news_filter']=calendar.status(s['symbol'])
                            if not s.get('trading_controls',{}).get('news_entry_block_enabled',True):
                                run['news_filter']={**run['news_filter'],'would_block':not run['news_filter']['allow_entry'],
                                    'allow_entry':True,'observed_status':run['news_filter']['status'],'status':'report_only',
                                    'execution_block_disabled_by_user':True}
                            plan=gate(plan,run['news_filter'])
                            try:
                                advice_path=ROOT/'.khorshid-research/portfolio.json'
                                advice=json.loads(advice_path.read_text()) if advice_path.stat().st_size<=200000 else {}
                            except (OSError,ValueError): advice={}
                            plan=portfolio_gate(plan,s,advice,time.time())
                            plan=entry_profile(plan,s,advice.get('news_analysis',{}).get(s['symbol'],{}),time.time())
                            plan=execution_gate(plan,ROOT,s,time.time(),advice=advice)
                            if plan.get('status')=='waiting_for_portfolio_allocation':
                                allocation_retry_bar=bar;allocation_retry_at=time.monotonic()+2
                            else:
                                allocation_retry_bar=None
                            run['entry_decision']={'utc':time.time(),'selected':chosen,'plan':plan,'news_mode':advice.get('news_mode'),
                                'profit_exit_mode':run.get('profit_exit_mode','standard'),
                                'experiment_id':run.get('experiment_id'),
                                'learning_regime':run.get('learning_regime'),'code_revision':run.get('code_revision'),
                                'market_context':market_context,'learning':learner.data['decisions'][-1],
                                'portfolio':advice.get('symbols',{}).get(s['symbol'],{}),
                                'news_analysis':advice.get('news_analysis',{}).get(s['symbol'],{}),
                                'headline_research':{'status':headlines.get('status','unavailable'),
                                    'analysis':headlines.get('symbols',{}).get(s['symbol'],{}),
                                    'evidence':headlines.get('evidence',[])}}
                            run['entry_decision']['market']={'bid':s['bid'],'ask':s['ask'],'equity':s['equity'],
                                'atr':atr[-1],'signal_bar':bar,'news':run['news_filter']}
                            memory.record_decision(run,s)
                            run['status']=plan.get('status','order_requested'); run['reason']=plan['reason']
                            if plan.get('action') and not (files()/'khorshid_demo_stop.flag').exists():
                                send(run,s,plan['action'],plan.get('direction',0),atr[-1],plan.get('strategy','none'),plan.get('tickets',()))
                                if plan['action']=='open': learner.attempted(chosen)
                            # Backtests are reporting work, not part of the order/lease path.
                            if screen_job is not None and screen_job.done():
                                try: screen_job.result()
                                except Exception as exc:
                                    memory.archive.save('worker_error',run['id'],{'utc':time.time(),'phase':'screening','error':str(exc)},
                                        {'account':run['login'],'symbol':run['symbol'],'experiment_id':run.get('experiment_id')})
                                    print('Screening report failed: '+str(exc),flush=True)
                                screen_job=None
                            if bars_since_screen>=24 and screen_job is None:
                                screen_job=screen_pool.submit(save_screen,dict(run),s)
                                bars_since_screen=0
                        try:
                            ack=json.loads((files()/'khorshid_demo_ack.json').read_text())
                            if ack.get('id')==run.get('last_request') and ack!=run.get('last_ack'):
                                run['last_ack']=ack
                                run['reason']=ack.get('note','')
                                if run['status']=='order_requested':
                                    run['status']='order_'+ack.get('status','unknown')
                                # Only this exact pre-order rejection is safe to retry.
                                # Timeouts, unknown execution and broker failures are never replayed.
                                if (ack.get('status')=='rejected' and ack.get('note')=='Portfolio allocation busy; no order sent'
                                        and 0<=s['bar_age_seconds']<=s['entry_window_seconds']):
                                    allocation_retry_bar=bar
                                    allocation_retry_at=time.monotonic()+2
                        except (FileNotFoundError,ValueError): pass
                    if not stopping:
                        run['weekly_close_paused']=s.get('weekly_close_paused',False)
                        run['weekly_schedule_known']=s.get('weekly_schedule_known')
                        run['weekly_close_server']=s.get('weekly_close_server')
                        run['weekly_reopen_server']=s.get('weekly_reopen_server')
                        run['tick_age_seconds']=s['tick_age_seconds']
                        if s.get('weekly_close_paused') is True:
                            run['status']='weekly_close_pending' if s['own_positions'] else 'weekly_close_pause'
                            run['reason']='Weekly close: waiting for robot positions to close' if s['own_positions'] else 'Weekly close: robot positions flat; waiting for reopening'
                        elif not 0<=s['tick_age_seconds']<=120 and s['own_positions']==0:
                            run['status']='market_closed_or_stale_quote'; run['reason']='No fresh quote; waiting for a tradable market'
                        elif not s['algo_enabled'] and s['own_positions']==0:
                            run['status']='algo_disabled'; run['reason']='Enable Algo Trading'
                        elif s['own_positions']:
                            run['status']='managing_demo_position'
                        elif run['status'] in ('market_closed_or_stale_quote','algo_disabled','managing_demo_position'):
                            run['status']='waiting_for_next_bar'; run['reason']='Waiting for next closed candle and a new entry signal'
                    save_run(run)
                except SnapshotUnavailable as exc:
                    memory.archive.save('worker_error',run['id'],{'phase':'snapshot','error':str(exc)},
                        {'account':run['login'],'symbol':run['symbol'],'experiment_id':run.get('experiment_id')})
                    # Do not renew the execution lease or send orders without valid data.
                    # The existing EA protection and manual stop marker stay authoritative.
                    if recovery.unavailable(time.time()):
                        run['connection_wait_since']=recovery.waiting_since
                        print('Waiting for MT5 connection: '+str(exc), flush=True)
                    (files()/'khorshid_demo_request.tsv').unlink(missing_ok=True)
                    run['reason']=str(exc)
                    run['status']='waiting_for_connection'
                    run['last_connection_error_utc']=time.time()
                    if (files()/'khorshid_demo_stop.flag').exists():
                        run['status']='stop_pending'
                        run['reason']='User requested stop while terminal unavailable; closure not confirmed'
                        save_run(run)
                        break
                    save_run(run)
                except (ValueError,OSError,KeyError,IndexError) as exc:
                    memory.archive.save('worker_error',run['id'],{'utc':time.time(),'phase':'execution','error':str(exc)},
                        {'account':run['login'],'symbol':run['symbol'],'experiment_id':run.get('experiment_id')})
                    failures+=1; run['reason']=str(exc); run['status']='data_unavailable'; save_run(run)
                    # Fail closed: no heartbeat refresh on error; terminal closes bot exposure on lease expiry.
                    if failures>=3 or (files()/'khorshid_demo_stop.flag').exists():
                        signal_stop(); run['status']='stop_pending'; break
                time.sleep(.5)
        except BaseException as exc:
            signal_stop(); run['status']='stop_pending'; run['reason']=str(exc)
            if not isinstance(exc,(KeyboardInterrupt,SystemExit)): raise
        finally:
            calendar.close()
            screen_pool.shutdown(wait=False,cancel_futures=True)
            run['ended_utc']=time.time(); save_run(run)
    report()

def direct_command(text):
    t=re.sub(r'[^\w\s]',' ',text.lower().replace('ي','ی').replace('ك','ک')).strip()
    t=re.sub(r'\s+',' ',t)
    for filler in ('خورشید ','لطفا ','لطفاً '):
        if t.startswith(filler): t=t[len(filler):].strip()
    if t in ('توقف کن','توقف کن توقف کن','ترید رو متوقف کن','معامله رو متوقف کن','توقف معاملات','stop trading','stop'):
        return 'stop'
    if t in ('تمرین دمو رو شروع کن','معامله دمو رو شروع کن','شروع تمرین دمو','start demo trading'): return 'start'
    if t in ('گزارش معاملات','نتیجه معاملات','گزارش تمرین','وضعیت تمرین دمو'): return 'report'
    return None

def direct_result(query):
    action=direct_command(query)
    if action is None: return None
    from ultimate_khorshid.agents.base import AgentResult
    r=MT5DemoTool().execute(action=action)
    return AgentResult(content=r.metadata.get('summary',r.content),tool_results=[r],metadata={'agent':'demo-controller','model':'deterministic'})

@ToolRegistry.register('mt5_multi_worker')
class MT5DemoTool(BaseTool):
    tool_id='mt5_multi_worker'
    @property
    def spec(self):
        return ToolSpec(name=self.tool_id,category='mt5',timeout_seconds=25,
            description='کنترل تمرین و معامله خودکار فقط حساب DEMO: start فقط برای استراتژی ثابتِ اعتبارسنجی و بازبینی‌شده است؛ پژوهش ده استراتژی مجوز معامله ایجاد نمی‌کند؛ stop توقف ورود و درخواست بستن فقط پوزیشن ربات و گزارش؛ report/status گزارش واقعی؛ catalog قواعد و منابع. اگر کاربر توقف خواست فوراً stop را اجرا کن. این نسخه ورود اکتشافی را مسدود می‌کند؛ بدون گزارش اعتبارسنجی مستقل و تأیید صریح، سفارش تازه نمی‌فرستد؛ تنظیم نسخهٔ جدید سقف هر ورود ۰٫۲۵٪ و مجموع حساب ۰٫۵٪ است؛ کیفیت قیمت و حد ضرر الزامی است. از mouse/shell برای دورزدن گاردهای معامله استفاده نکن. توقف قطعی پوزیشن را فقط با snapshot تازه و تعداد باز صفر اعلام کن. سود یا اجرای ابزار را جعل نکن.',
            parameters={'type':'object','properties':{'action':{'type':'string','enum':['start','stop','status','report','catalog']}},'required':['action']})
    def execute(self,**p):
        try:
            action=p.get('action')
            if action=='start': out=start()
            elif action=='stop': out=stop()
            elif action in ('report','status'): out=report()
            elif action=='catalog': out={'strategies':CATALOG,'rules':RULES,'summary':'۱۰ فرضیه قابل‌آزمایش؛ بهترین‌بودن آن‌ها ادعا نشده است.'}
            else: raise ValueError('Unknown action')
            return ToolResult(tool_name=self.tool_id,content=json.dumps(out,ensure_ascii=False),metadata=out)
        except (ValueError,OSError,sqlite3.Error,KeyError) as exc:
            return ToolResult(tool_name=self.tool_id,content=str(exc),success=False)

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('action',choices=['start','stop','status','report','catalog','run','resume']); a=p.parse_args()
    if a.action in ('run','resume'): run_loop(resume=a.action=='resume'); return 0
    r=MT5DemoTool().execute(action=a.action); print(json.dumps(r.metadata,ensure_ascii=False,indent=2) if r.success else r.content); return 0 if r.success else 1
if __name__=='__main__': raise SystemExit(main())
