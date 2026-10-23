"""Economic-calendar entry gate. No network on the execution loop."""
import json, time, threading, urllib.request, urllib.error, os, fcntl
from pathlib import Path
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
URL='https://nfs.faireconomy.media/ff_calendar_thisweek.json'
CURRENCIES={'XAUUSD':{'USD'},'EURUSD':{'EUR','USD'},'USDJPY':{'USD','JPY'}}
def parse(rows):
    if not isinstance(rows,list) or not rows: raise ValueError('Empty/invalid calendar')
    events=[]
    for r in rows:
        dt=datetime.fromisoformat(r['date'])
        if dt.tzinfo is None: raise ValueError('Calendar timezone missing')
        events.append({'title':str(r['title'])[:250],'currency':r['country'],'impact':r['impact'],'utc':dt.timestamp()})
    return events

def assess(events,fetched,symbol,now,error='',controls=None):
    controls=controls or {}
    before,after=controls.get('news_before_minutes',30),controls.get('news_after_minutes',15)
    base={'source':URL,'fetched_utc':fetched,'error':error,'before_minutes':before,'after_minutes':after}
    if not events or not 0<=now-fetched<=3600:
        return {**base,'allow_entry':False,'status':'calendar_unavailable','reason':'Economic calendar unavailable or older than one hour'}
    # Reject a feed for a different week, even when just downloaded.
    week=datetime.fromtimestamp(now,timezone.utc).isocalendar()[:2]
    if not any(datetime.fromtimestamp(e['utc'],timezone.utc).isocalendar()[:2]==week for e in events):
        return {**base,'allow_entry':False,'status':'calendar_outdated','reason':'Calendar does not cover current week'}
    relevant=[e for e in events if e['impact']=='High' and e['currency'] in CURRENCIES[symbol]|{'All'}]
    blocked=[e for e in relevant if e['utc']-before*60<=now<=e['utc']+after*60]
    upcoming=sorted([e for e in relevant if e['utc']>=now-900],key=lambda e:e['utc'])[:5]
    return {**base,'allow_entry':not blocked,'status':'news_window' if blocked else 'calendar_clear',
            'reason':'High-impact economic event entry window' if blocked else 'No relevant high-impact event in entry exclusion window',
            'blocking_events':blocked,'next_events':upcoming}

def read_cache(folder):
    try:
        data=json.loads((folder/'calendar.json').read_text())
        if data.get('source')!=URL: return {}
        return data
    except (OSError,ValueError): return {}

def write_cache(folder,data):
    tmp=folder/('calendar.'+str(os.getpid())+'.tmp')
    try:
        with tmp.open('w') as f:
            json.dump(data,f,allow_nan=False); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,folder/'calendar.json')
    finally: tmp.unlink(missing_ok=True)

def refresh_shared(folder,fetch=None,now=None):
    folder=Path(folder); folder.mkdir(parents=True,exist_ok=True)
    now=time.time() if now is None else now
    with (folder/'calendar.lock').open('a') as lock:
        try: fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: return read_cache(folder)
        data=read_cache(folder)
        if now < data.get('next_fetch_utc',0): return data
        # Persist cooldown before I/O so a crash cannot cause a request storm.
        data.update(source=URL,next_fetch_utc=now+900)
        write_cache(folder,data)
        try:
            if fetch is None:
                req=urllib.request.Request(URL,headers={'User-Agent':'KhorshidDemoCalendar/1.1'})
                with urllib.request.urlopen(req,timeout=10) as r: raw=r.read(2000001)
                if len(raw)>2000000: raise ValueError('Oversized calendar')
                rows=json.loads(raw)
            else: rows=fetch()
            data.update(events=parse(rows),fetched_utc=now,error='',failures=0)
        except Exception as exc:
            failures=data.get('failures',0)+1
            delay=min(21600,900*2**min(failures-1,5))
            if isinstance(exc,urllib.error.HTTPError):
                retry=exc.headers.get('Retry-After','') if exc.headers else ''
                try: delay=max(delay,float(retry))
                except ValueError:
                    try: delay=max(delay,parsedate_to_datetime(retry).timestamp()-now)
                    except (ValueError,TypeError,OverflowError): pass
            data.update(error=type(exc).__name__+': '+str(exc)[:200],failures=failures,next_fetch_utc=now+delay)
        write_cache(folder,data)
        return data

class Calendar:
    def __init__(self):
        self.folder=Path(__file__).resolve().parents[2]/'.khorshid-multi'/'shared-news'
        self.stop_event=threading.Event()
        self.thread=threading.Thread(target=self._run,daemon=True); self.thread.start()
    def _run(self):
        while not self.stop_event.is_set():
            try: refresh_shared(self.folder)
            except (OSError,ValueError): pass
            self.stop_event.wait(2)
    def status(self,symbol):
        from ultimate_khorshid.tools.trading_controls import read
        data=read_cache(self.folder)
        result=assess(data.get('events',[]),data.get('fetched_utc',0),symbol,time.time(),data.get('error',''),
            read(Path(__file__).resolve().parents[2]))
        result.update(shared_calendar=True,next_fetch_utc=data.get('next_fetch_utc',0))
        return result
    def close(self): self.stop_event.set()

def gate(plan,news):
    if plan.get('action')=='open' and not news['allow_entry']:
        return {'status':news['status'],'reason':news['reason']}
    return plan
