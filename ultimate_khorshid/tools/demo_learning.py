"""Persistent forward-paper experience and demo exploration selection. No model training."""
import json
import math
import os
from pathlib import Path
import time
import uuid
from ultimate_khorshid.tools.demo_lab import CATALOG

NAMES=[x[0] for x in CATALOG]

def atomic(path,data):
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    path.parent.mkdir(parents=True,exist_ok=True)
    try:
        with tmp.open('w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,allow_nan=False); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,path)
    finally: tmp.unlink(missing_ok=True)

class Experience:
    def __init__(self,path):
        self.path=Path(path)
        if self.path.exists():
            self.data=json.loads(self.path.read_text())
            if self.data.get('version')!=1: raise ValueError('Unknown experience version')
        else:
            self.data={'version':1,'stats':{k:{'paper_n':0,'paper_mean_r':0.,'demo_n':0,'demo_mean_r':0.,'demo_net':0.,'attempts':0} for k in NAMES},'books':{},'live_seen':[],'events':[],'decisions':[]}
        # Preserve legacy approximate results for reporting, not verified scoring.
        for st in self.data['stats'].values():
            for key,value in {'verified_demo_n':0,'verified_demo_mean_r':0.,'verified_demo_net':0.}.items():
                st.setdefault(key,value)
        self.data.setdefault('verified_seen',[])
        self.data['learning_policy_version']=2
    def event(self,event):
        event['recorded_utc']=time.time()
        self.data['events'].append(event)
        # Full history append-only; compact state retains the latest 100 entries.
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.path.with_suffix('.jsonl').open('a',encoding='utf-8') as f:
            f.write(json.dumps(event,ensure_ascii=False,allow_nan=False)+'\n')
        self.data['events']=self.data['events'][-100:]
    def save(self): atomic(self.path,self.data)
    def activate(self,s):
        for k,b in self.data.get('books',{}).items():
            if b.get('position'): self.event({'kind':'paper_abandoned_on_restart','strategy':k,'reason':'No continuous observation across restart; not scored'})
        self.data['books']={k:{'equity':self.data.get('books',{}).get(k,{}).get('equity',100000.),'position':None} for k in NAMES}
        self.data['cursor']=s['bars'][-1]['time']; self.data['observed_utc']=time.time()
        self.data['period_seconds']=s['period_seconds']; self.data['account']=s['login']
        self.save()
    def reward(self,strategy,kind,r,net=0):
        if not math.isfinite(r): raise ValueError('Invalid reward')
        st=self.data['stats'][strategy]; before=self.score(strategy,explore=False)
        key=kind+'_n'; avg=kind+'_mean_r'; st[key]+=1
        # Bounded EWMA limits the effect of a single windfall or bad fill; recent evidence matters more.
        clipped=max(-3.,min(3.,r)); alpha=1/min(st[key],20)
        st[avg]+=alpha*(clipped-st[avg])
        if kind in ('demo','verified_demo'): st[kind+'_net']+=net
        return before,self.score(strategy,explore=False)
    def score(self,k,explore=True):
        s=self.data['stats'][k]; pn=min(s['paper_n'],20); dn=min(s['verified_demo_n'],20)
        evidence=(pn*s['paper_mean_r']+3*dn*s['verified_demo_mean_r'])/(pn+3*dn) if pn+dn else 0.
        total=sum(x['attempts'] for x in self.data['stats'].values())
        bonus=.35*math.sqrt(math.log(2+total)/(1+s['attempts'])) if explore else 0.
        return evidence+bonus
    def choose(self,signals):
        candidates=[k for k in NAMES if signals[k][-1] in (-1,1)]
        scores={k:round(self.score(k),6) for k in candidates}
        selected=max(candidates,key=lambda k:(scores[k],-self.data['stats'][k]['attempts'],-NAMES.index(k))) if candidates else None
        details={k:{'paper_results':self.data['stats'][k]['paper_n'],'demo_results':self.data['stats'][k]['verified_demo_n'],'legacy_demo_results':self.data['stats'][k]['demo_n'],'experience_score':round(self.score(k,False),6),'exploration_bonus':round(self.score(k)-self.score(k,False),6),'total_score':scores[k]} for k in candidates}
        d={'score_details':details,'utc':time.time(),'candidates':scores,'selected':selected,'reason':'experience score + exploration bonus among current signals' if selected else 'No closed-bar entry signal'}
        self.data['decisions']=(self.data['decisions']+[d])[-30:]; self.event({'kind':'decision',**d}); self.save()
        return selected
    def attempted(self,strategy):
        self.data['stats'][strategy]['attempts']+=1; self.save()
    def advance(self,bars,signals,atr,point,now=None):
        now=time.time() if now is None else now
        cursor=self.data['cursor']; unseen=[i for i,b in enumerate(bars) if b['time']>cursor]
        if not unseen: return
        # Missed bars are not falsely described as forward experience.
        continuous=len(unseen)==1 and unseen[0]>0 and bars[unseen[0]-1]['time']==cursor and now-self.data['observed_utc']<=self.data['period_seconds']*2+120
        if not continuous:
            self.event({'kind':'observation_gap','bars':len(unseen),'reason':'Skipped; no retroactive forward trades'})
            for b in self.data['books'].values(): b['position']=None
        else:
            i=unseen[0]; bar=bars[i]; spread=max(bar['spread']*point,point*2)
            for name in NAMES:
                book=self.data['books'][name]; p=book['position']; sig=signals[name][i-1]
                def close(price,why):
                    nonlocal p
                    days=max(0,(bar['time']-p['time'])/86400)
                    fill=price+(spread if p['side']<0 else 0)-p['side']*2*point
                    r=p['side']*(fill-p['entry'])/p['distance']-.10-.02*days
                    pnl=p['risk_cash']*r; book['equity']=max(0,book['equity']+pnl)
                    before,after=self.reward(name,'paper',r)
                    self.event({'kind':'paper_close','strategy':name,'entry_bar':p['time'],'exit_bar':bar['time'],'reason':why,'r':r,'net_simulated':pnl,'score_before':before,'score_after':after})
                    p=None; book['position']=None
                if p:
                    p['bars']+=1
                    if sig==-p['side'] or p['bars']>=24: close(bar['open'],'opposite_signal_or_timeout')
                if p is None and sig and atr[i-1]>point*10 and spread<=atr[i-1]*.2:
                    distance=2*atr[i-1]; entry=bar['open']+(spread if sig>0 else 0)+sig*point*2
                    p={'side':sig,'entry':entry,'stop':entry-sig*distance,'target':entry+sig*3*atr[i-1],'distance':distance,'time':bar['time'],'bars':0,'risk_cash':book['equity']*.0005}
                    book['position']=p
                    self.event({'kind':'paper_open','strategy':name,'signal_bar':bars[i-1]['time'],'entry_bar':bar['time'],'side':sig,'entry':entry,'stop':p['stop'],'target':p['target']})
                if p:
                    ask_spread=spread if p['side']<0 else 0
                    low,high,op=bar['low']+ask_spread,bar['high']+ask_spread,bar['open']+ask_spread
                    hit_stop=low<=p['stop'] if p['side']>0 else high>=p['stop']
                    hit_target=high>=p['target'] if p['side']>0 else low<=p['target']
                    if hit_stop or hit_target:
                        price=(min(op,p['stop']) if p['side']>0 else max(op,p['stop'])) if hit_stop else p['target']
                        close(price-ask_spread,'stop' if hit_stop else 'target')
        self.data['cursor']=bars[-1]['time']; self.data['observed_utc']=now; self.save()
    def learn_live(self,groups,risk_cash,open_ids):
        # risk_cash is retained for callers of the old API; never a new reward denominator.
        dirty=False
        for ident,g in groups.items():
            ident=str(ident); k=g['strategy']; account=g.get('account')
            token=f'{account}:{ident}'
            if (token in self.data['verified_seen'] or ident in self.data['live_seen'] or ident in open_ids
                    or not g.get('learning_eligible') or not g.get('closed_complete') or k not in NAMES
                    or account!=self.data.get('account')): continue
            r=g.get('normalized_reward')
            if not isinstance(r,(int,float)) or isinstance(r,bool) or not math.isfinite(r): continue
            before,after=self.reward(k,'verified_demo',r,g['net'])
            dirty=True
            self.data['verified_seen'].append(token)
            self.event({'kind':'verified_demo_close','event_id':token,'position_id':ident,'account':account,
                        'strategy':k,'net':g['net'],'normalized_reward':r,'risk_cash':g['risk_cash'],
                        'normalization':g['normalization'],'deal_tickets':g['deal_tickets'],
                        'score_before':before,'score_after':after})
        if dirty: self.save()
    def summary(self):
        return {'mode':'demo_exploration','paper_closed':sum(v['paper_n'] for v in self.data['stats'].values()),
            'demo_closed_learned':sum(v['verified_demo_n'] for v in self.data['stats'].values()),
            'legacy_demo_closed_approximate':sum(v['demo_n'] for v in self.data['stats'].values()),
            'learning_policy_version':2,
            'paper_open':sum(bool(b['position']) for b in self.data['books'].values()),'stats':self.data['stats'],
            'latest_events':self.data['events'][-12:],'latest_decision':self.data['decisions'][-1] if self.data['decisions'] else None,
            'note':'Paper simulation, legacy approximate demo results and evidence-checked demo results are separate. New scores exclude legacy approximate rewards. Entry SL risk remains an estimate. Adapts strategy weights, not Gemini model weights.'}
