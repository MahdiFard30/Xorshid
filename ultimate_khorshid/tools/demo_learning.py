"""Persistent forward-paper experience and demo exploration selection. No model training."""
import json
import math
import os
import sqlite3
from pathlib import Path
import time
import uuid
import hashlib
from ultimate_khorshid.tools.demo_lab import CATALOG
from ultimate_khorshid.tools.exit_rules import POLICY_VERSION, outcome_policy
from ultimate_khorshid.tools.execution_model import new_book, step

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
            self.data={'version':1,'exit_policy_version':POLICY_VERSION,'stats':{k:{'paper_n':0,'paper_mean_r':0.,'demo_n':0,'demo_mean_r':0.,'demo_net':0.,'attempts':0} for k in NAMES},'books':{},'live_seen':[],'events':[],'decisions':[]}
        # Preserve legacy approximate results for reporting, not verified scoring.
        for st in self.data['stats'].values():
            for key,value in {'verified_demo_n':0,'verified_demo_mean_r':0.,'verified_demo_net':0.}.items():
                st.setdefault(key,value)
        self.data.setdefault('policy_archives',[])
        if self.data.get('exit_policy_version') != POLICY_VERSION:
            self.data['policy_archives'].append({'exit_policy_version':self.data.get('exit_policy_version',0),
                'stats':json.loads(json.dumps(self.data['stats'])),'books':self.data.get('books',{})})
            for st in self.data['stats'].values():
                for field in ('paper_n','paper_mean_r','verified_demo_n','verified_demo_mean_r','verified_demo_net','attempts'):
                    st[field]=0
            self.data['books']={}
            self.data['exit_policy_version']=POLICY_VERSION
        self.data.setdefault('verified_seen',[])
        self.data['learning_policy_version']=2
        self.context_model=None
        self.regime=None
        self.stats=self.data['stats']
    def set_regime(self,regime):
        self.regime=regime or None
        if not self.regime:self.stats=self.data['stats']
        else:
            regimes=self.data.setdefault('regimes',{})
            if self.regime not in regimes:
                regimes[self.regime]={'stats':{k:{field:0 for field in st} for k,st in self.data['stats'].items()},
                                      'created_utc':time.time(),'note':'Separate policy evidence; previous history retained'}
            self.stats=regimes[self.regime]['stats']
        self.context_model=None
    def context_path(self):
        suffix='.'+hashlib.sha256(self.regime.encode()).hexdigest()[:12] if self.regime else ''
        return self.path.with_suffix(f'.context.v{POLICY_VERSION}{suffix}.sqlite')
    def contextual(self):
        if self.context_model is None:
            from ultimate_khorshid.tools.market_learning import ContextModel
            self.context_model=ContextModel(self.context_path(),self.data.get('account'))
        return self.context_model
    def event(self,event):
        event.setdefault('learning_regime',self.regime)
        event['recorded_utc']=time.time()
        from ultimate_khorshid.tools.history_archive import Archive
        if not hasattr(self,'event_archive'):self.event_archive=Archive(self.path.with_suffix('.events.sqlite'))
        self.event_archive.save('learning_event',event.get('event_id') or self.path.stem,event,
            {'account':self.data.get('account'),'learning_regime':self.regime})
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
        self.data['books']={k:new_book(self.data.get('books',{}).get(k,{}).get('equity',100000.)) for k in NAMES}
        self.data['cursor']=s['bars'][-1]['time']; self.data['observed_utc']=time.time()
        self.data['period_seconds']=s['period_seconds']; self.data['account']=s['login']
        self.context_model=None
        self.save()
    def reward(self,strategy,kind,r,net=0):
        if not math.isfinite(r): raise ValueError('Invalid reward')
        st=self.stats[strategy]; before=self.score(strategy,explore=False)
        key=kind+'_n'; avg=kind+'_mean_r'; st[key]+=1
        # Bounded EWMA limits the effect of a single windfall or bad fill; recent evidence matters more.
        clipped=max(-3.,min(3.,r)); alpha=1/min(st[key],20)
        st[avg]+=alpha*(clipped-st[avg])
        if kind in ('demo','verified_demo'): st[kind+'_net']+=net
        return before,self.score(strategy,explore=False)
    def score(self,k,explore=True):
        s=self.stats[k]; pn=min(s['paper_n'],20); dn=min(s['verified_demo_n'],20)
        evidence=(pn*s['paper_mean_r']+3*dn*s['verified_demo_mean_r'])/(pn+3*dn) if pn+dn else 0.
        total=sum(x['attempts'] for x in self.stats.values())
        bonus=.35*math.sqrt(math.log(2+total)/(1+s['attempts'])) if explore else 0.
        return evidence+bonus
    def rank(self,signals,context=None,news_adjustments=None,allowed=None):
        candidates=[k for k in NAMES if (allowed is None or k in allowed) and signals.get(k,[0])[-1] in (-1,1)]
        try:
            assessments={k:self.contextual().assess(k,context,signals[k][-1]) for k in candidates} if context else {}
            self.data.pop('context_error',None)
        except (sqlite3.Error,OSError,ValueError) as exc:
            assessments={}
            self.data['context_error']=type(exc).__name__+': '+str(exc)
        paused=[k for k in candidates if assessments.get(k,{}).get('paused')]
        candidates=[k for k in candidates if k not in paused]
        news_adjustments=news_adjustments or {}
        raw_scores={k:self.score(k)+assessments.get(k,{}).get('adjustment',0)+max(-.15,min(.15,news_adjustments.get(k,0))) for k in candidates}
        # Exploration orders eligible candidates; it is not profit evidence.
        # Keep it in the ranking, but do not let it rescue negative evidence.
        evidence_scores={k:self.score(k,explore=False)+assessments.get(k,{}).get('adjustment',0)+max(-.15,min(.15,news_adjustments.get(k,0))) for k in candidates}
        scores={k:round(value,6) for k,value in raw_scores.items()}
        evidence_rejected=[k for k in candidates if evidence_scores[k]<0]
        score_rejected=[k for k in candidates if raw_scores[k]<0 or evidence_scores[k]<0]
        eligible=[k for k in candidates if k not in score_rejected]
        selected=max(eligible,key=lambda k:(scores[k],-self.stats[k]['attempts'],-NAMES.index(k))) if eligible else None
        details={k:{'paper_results':self.stats[k]['paper_n'],'demo_results':self.stats[k]['verified_demo_n'],'legacy_demo_results':self.data['stats'][k]['demo_n'],'experience_score':round(self.score(k,False),6),'exploration_bonus':round(self.score(k)-self.score(k,False),6),'total_score':scores[k]} for k in candidates}
        for k in candidates:
            pn=min(self.stats[k]['paper_n'],20);dn=3*min(self.stats[k]['verified_demo_n'],20);total=pn+dn
            details[k].update(paper_mean_r=self.stats[k]['paper_mean_r'],verified_demo_mean_r=self.stats[k]['verified_demo_mean_r'],
                unrounded_total_score=raw_scores[k],entry_score_eligible=k not in score_rejected,
                evidence_score=evidence_scores[k],
                entry_score_rejections=(["negative_evidence_without_exploration"] if evidence_scores[k]<0 else [])+
                    (["negative_final_score"] if raw_scores[k]<0 else []),
                paper_weight=pn/total if total else 0,verified_demo_weight=dn/total if total else 0,
                context_adjustment=assessments.get(k,{}).get('adjustment',0),
                news_adjustment=max(-.15,min(.15,news_adjustments.get(k,0))))
        d={'score_details':details,'learning_regime':self.regime,'utc':time.time(),'candidates':scores,'selected':selected,
           'score_rejected':score_rejected,'entry_score_floor':0.,
           'evidence_rejected':evidence_rejected,'evidence_score_floor':0.,
           'market_context':context,'context_assessments':assessments,'context_paused':paused,
           'context_error':self.data.get('context_error'),'news_adjustments':news_adjustments,
           'reason':'experience score + exploration bonus + bounded context evidence' if selected and context
                    else 'experience score + exploration bonus among current signals' if selected
                    else 'No non-negative strategy evidence without exploration; entry declined' if evidence_rejected
                    else 'No non-negative final strategy score; entry declined' if score_rejected
                    else 'Negative context evidence paused all current signals' if paused else 'No closed-bar entry signal'}
        return d
    def choose(self,signals,context=None,news_adjustments=None):
        d=self.rank(signals,context,news_adjustments)
        self.data['decisions']=(self.data['decisions']+[d])[-30:]; self.event({'kind':'decision',**d}); self.save()
        return d['selected']
    def attempted(self,strategy):
        self.stats[strategy]['attempts']+=1; self.save()
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
            i=unseen[0]; bar=bars[i]
            for name in NAMES:
                book=self.data['books'][name]
                events=step(book,{**bar,'period_seconds':self.data['period_seconds']},signals[name][i-1],atr[i-1],point)
                for event in events:
                    if event['kind']=='close':
                        before,after=self.reward(name,'paper',event['r'])
                        self.event({'kind':'paper_close','strategy':name,**{k:v for k,v in event.items() if k!='kind'},
                                    'score_before':before,'score_after':after})
                    else:
                        self.event({'kind':'paper_'+event['kind'],'strategy':name,**{k:v for k,v in event.items() if k!='kind'}})
        self.data['cursor']=bars[-1]['time']; self.data['observed_utc']=now; self.save()
    def learn_live(self,groups,risk_cash,open_ids):
        groups={k:g for k,g in groups.items() if outcome_policy(g)==POLICY_VERSION}
        if self.regime:groups={k:g for k,g in groups.items() if g.get('learning_regime')==self.regime}
        # risk_cash is retained for callers of the old API; never a new reward denominator.
        if self.data.get('account') is not None:
            try:
                self.contextual().observe({k:g for k,g in groups.items() if str(k) not in self.data['live_seen']},open_ids)
            except (sqlite3.Error,OSError,ValueError) as exc:
                self.data['context_error']=type(exc).__name__+': '+str(exc)
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
        from ultimate_khorshid.tools.market_learning import ContextModel
        try:
            context_summary=ContextModel.summary(self.context_path(),self.data.get('account'))
        except (sqlite3.Error,OSError,ValueError) as exc:
            context_summary={'available':False,'error':type(exc).__name__+': '+str(exc)}
        return {'mode':'persistent_policy_scoped_experience','learning_regime':self.regime,
            'prior_regimes_retained':list(self.data.get('regimes',{})),
            'paper_closed':sum(v['paper_n'] for v in self.stats.values()),
            'context_learning':context_summary,
            'demo_closed_learned':sum(v['verified_demo_n'] for v in self.stats.values()),
            'legacy_demo_closed_approximate':sum(v['demo_n'] for v in self.data['stats'].values()),
            'learning_policy_version':2,'exit_policy_version':POLICY_VERSION,
            'archived_policy_demo_closed':sum(sum(st.get('verified_demo_n',0) for st in archive['stats'].values()) for archive in self.data.get('policy_archives',[])),
            'paper_open':sum(bool(b['position']) for b in self.data['books'].values()),'stats':self.stats,
            'latest_events':self.data['events'][-12:],'latest_decision':self.data['decisions'][-1] if self.data['decisions'] else None,
            'note':'Paper simulation, legacy approximate demo results and evidence-checked demo results are separate. New scores exclude legacy approximate rewards. Entry SL risk remains an estimate. Adapts strategy weights, not Gemini model weights.'}
