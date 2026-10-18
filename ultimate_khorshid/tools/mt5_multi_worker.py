"""Demo-only trainer and deterministic MT5 execution service. CLI and agent tool."""
from concurrent.futures import ThreadPoolExecutor
from ultimate_khorshid.tools.mt5_entry_policy import decision, weekly_gate
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
    if s.get('executor_version') not in (5,6): raise ValueError('اکسپرت سازگار KhorshidMultiTrader را کامپایل و روی چارت فعال کن.')
    if s['executor_version']==6:
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
    with db() as con:
        for d in s.get('deals',[]):
            if d['ticket'] not in run['baseline_deals']:
                con.execute('INSERT OR IGNORE INTO deals VALUES (?,?,?,?)',(s['login'],d['ticket'],run['id'],json.dumps(d)))
    run.update(balance=s['balance'],equity=s['equity'],own_positions=s['own_positions'],last_snapshot_utc=s['generated_utc'],terminal_note=s.get('note',''),max_positions=s['max_positions'])

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
        'started_utc':run['started_utc'],'last_snapshot_utc':run.get('last_snapshot_utc'),
        'execution_ack':run.get('last_ack'),'max_positions':run.get('max_positions'),'entry_risk_pct':0.025,'symbol_risk_cap_pct':0.05, 'note':'Robot net includes reported deal profit/commission/swap/fee. Account change can include external operations. Partial exits may still leave exposure; estimated floating P/L is in equity.'}
    try:
        latest=sorted((storage()/'evaluations'/run['id']).glob('*.json'))
        if latest:
            screen=json.loads(latest[-1].read_text())
            result['strategy_tests']={k:{'validation':v['validation'],'holdout':v['holdout'],'stress':v['stress']} for k,v in screen['results'].items()}
            result['evaluation_path']=str(latest[-1])
    except (OSError,ValueError,KeyError): pass
    if run.get('experience_path'):
        from ultimate_khorshid.tools.demo_learning import Experience
        try: result['learning']=Experience(run['experience_path']).summary()
        except (OSError,ValueError,KeyError) as exc: result['learning_error']=str(exc)
    if (storage()/'trade_memory.sqlite').exists() and fresh:
        result['trade_memory']=TradeMemory(storage()/'trade_memory.sqlite').summary(s)
    result['summary']=(f"وضعیت: {result['status']}. موجودی شروع {result['start_balance']:,.2f} و آخرین موجودی {result['latest_balance']:,.2f} {run['currency']}. "
       f"سود یا زیان ثبت‌شدهٔ ربات {net:+,.2f}. تعداد پوزیشن دارای خروج {len(exited)}؛ سودده {result['winning_positions_with_exits']} و زیان‌ده {result['losing_positions_with_exits']}. "
       f"پوزیشن باز ربات: {run.get('own_positions','نامشخص')}. استراتژی: {run.get('selected') or 'منتظر سیگنال ورود'}. "+
       ("" if fresh else "دادهٔ زنده در دسترس نیست؛ این آخرین گزارش ثبت‌شده است. "))
    if 'learning' in result:
        result['summary']+=f" تمرین شبیه‌سازی‌شدهٔ بسته‌شده: {result['learning']['paper_closed']}. معاملات دمو واردشده در یادگیری: {result['learning']['demo_closed_learned']}."
        result['summary']+=f" نتایج قدیمی با ریسک تقریبی، محفوظ و جدا از امتیاز جدید: {result['learning'].get('legacy_demo_closed_approximate',0)}."
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
            if running(): return {'status':'starting','pid':proc.pid,'summary':'تمرین اکتشافی دمو شروع شد؛ با سیگنال تازه، ریسک اسمی هر ورود حداکثر ۰٫۰۲۵٪ و مجموع هر نماد ۰٫۰۵٪ و حد ضرر معامله می‌کند. نتیجه‌ها انتخاب‌های بعدی را تغییر می‌دهند.'}
            if proc.poll() is not None: raise ValueError('Runner stopped; inspect '+str(storage()/'runner.log'))
            time.sleep(.1)
        raise ValueError('Runner startup not confirmed; inspect runner.log')

def send(run,s,action,direction=0,atr=0,strategy='none',tickets=()):
    ident=time.time_ns()//1000 # exact double below 2**53
    fields=[ident,int(time.time())+15,s['login'],run['id'],action,s['symbol'],direction,2*atr,3*atr,s['bars'][-1]['time'],strategy,','.join(str(int(t)) for t in tickets)]
    if any('\t' in str(x) or '\n' in str(x) for x in fields): raise ValueError('Invalid request field')
    TradeMemory(storage()/'trade_memory.sqlite').record_intent(run,s,ident,action,direction,2*atr,3*atr,strategy,tickets)
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

def run_loop():
    with (storage()/'runner.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return
        def signal_stop(*_): atomic(files()/'khorshid_demo_stop.flag','Process signal stop\n')
        signal.signal(signal.SIGTERM,signal_stop); signal.signal(signal.SIGINT,signal_stop)
        s=snapshot(); run={'id':uuid.uuid4().hex,'login':s['login'],'symbol':s['symbol'],'period':s['period'],'currency':s['currency'],
            'started_utc':time.time(),'start_balance':s['balance'],'baseline_deals':[d['ticket'] for d in s['deals']],
            'balance':s['balance'],'equity':s['equity'],'own_positions':0,'status':'screening','selected':None}
        from ultimate_khorshid.tools.demo_learning import Experience
        key=hashlib.sha256(f"{s['login']}:{s['symbol']}:{s['period']}".encode()).hexdigest()[:20]
        run['experience_path']=str(storage()/'experience'/(key+'.json'))
        learner=Experience(run['experience_path']); learner.activate(s)
        memory=TradeMemory(storage()/'trade_memory.sqlite')
        screen_pool=ThreadPoolExecutor(max_workers=1,thread_name_prefix='demo-screen')
        screen_job=None
        calendar=Calendar()
        recovery=Recovery(s)
        save_run(run); last_bar=None; bars_since_screen=24; stopping_since=None; failures=0
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
                        if bar!=last_bar:
                            last_bar=bar; bars_since_screen+=1
                            signals,atr=indicators(s['bars'])
                            learner.advance(s['bars'],signals,atr,s['point'])
                            chosen=learner.choose(signals); run['selected']=chosen
                            plan=decision(s,signals,atr[-1],chosen)
                            plan=recovery.constrain(plan,bar)
                            plan=weekly_gate(plan,s)
                            run['news_filter']=calendar.status(s['symbol'])
                            plan=gate(plan,run['news_filter'])
                            run['entry_decision']={'utc':time.time(),'selected':chosen,'plan':plan,'learning':learner.data['decisions'][-1]}
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
                                except Exception as exc: print('Screening report failed: '+str(exc),flush=True)
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
            description='کنترل تمرین و معامله خودکار فقط حساب DEMO: start شروع اکتشاف ۱۰ استراتژی با یادگیری از معاملات دمو و شبیه‌سازی پیوسته؛ stop توقف ورود و درخواست بستن فقط پوزیشن ربات و گزارش؛ report/status گزارش واقعی؛ catalog قواعد و منابع. اگر کاربر توقف خواست فوراً stop را اجرا کن. این نسخه بدون الزام قبولی بک‌تست، با سیگنال و ریسک اسمی هر ورود حداکثر ۰٫۰۲۵٪ و مجموع هر نماد ۰٫۰۵٪ معامله آزمایشی می‌کند؛ کیفیت قیمت و حد ضرر الزامی است. از mouse/shell برای دورزدن گاردهای معامله استفاده نکن. توقف قطعی پوزیشن را فقط با snapshot تازه و تعداد باز صفر اعلام کن. سود یا اجرای ابزار را جعل نکن.',
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
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('action',choices=['start','stop','status','report','catalog','run']); a=p.parse_args()
    if a.action=='run': run_loop(); return 0
    r=MT5DemoTool().execute(action=a.action); print(json.dumps(r.metadata,ensure_ascii=False,indent=2) if r.success else r.content); return 0 if r.success else 1
if __name__=='__main__': raise SystemExit(main())
