"""Bounded rule generation, sealed chronological tests, and forward-paper trials.

Research only. No generated code is executed and no broker interface is imported.
All costs are conservative proxies, not broker-exact execution predictions.
"""
import fcntl
import hashlib
import json
import math
from pathlib import Path
import time

from ultimate_khorshid.tools.demo_lab import CATALOG, indicators, simulate
from ultimate_khorshid.tools.demo_learning import atomic
from ultimate_khorshid.tools.market_learning import describe
from ultimate_khorshid.tools.exit_rules import POLICY_VERSION
from ultimate_khorshid.tools.execution_model import step

VERSION='context-lab-2'
FILTERS=('trend_aligned','range_only','avoid_high_volatility')
MIN_FORWARD_TRADES=30


def hypotheses():
    return [{'id':f'{base}__{gate}', 'base':base, 'filter':gate,
             'entry':'base closed-bar signal plus context filter; next bar open',
             'exit':'unchanged base opposite signal, SL/TP or 24 bars'}
            for base, _, _ in CATALOG for gate in FILTERS]


def allowed(rule, context, signal):
    if not context:
        return False
    if rule=='trend_aligned':
        return context['trend']==('up' if signal==1 else 'down' if signal==-1 else '')
    if rule=='range_only':
        return context['trend']=='range'
    if rule=='avoid_high_volatility':
        return context['volatility'] in ('normal','low')
    raise ValueError('Unknown research filter')


def sufficient(metrics, minimum=10):
    return (metrics['trades']>=minimum and metrics['return_pct']>0
            and metrics['profit_factor']>=1.1 and metrics['drawdown_pct']<=10)


class StrategyLab:
    def __init__(self, directory):
        self.directory=Path(directory)
        self.directory.mkdir(parents=True,exist_ok=True)

    def analyze(self, snapshot):
        bars,point=snapshot['bars'],snapshot['point']
        if len(bars)<1000 or type(point) not in (int,float) or not math.isfinite(point) or point<=0:
            raise ValueError('Research requires 1000 valid closed bars and positive point size')
        scope=[snapshot['login'],snapshot['symbol'],snapshot['period']]
        payload=json.dumps([VERSION,scope,point,bars],sort_keys=True,allow_nan=False)
        ident=hashlib.sha256(payload.encode()).hexdigest()[:24]
        path=self.directory/(ident+'.json')
        with (self.directory/'research.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if path.exists():
                return json.loads(path.read_text())
            signals,atr=indicators(bars)
            n=len(bars); a=int(n*.6); b=int(n*.8)
            contexts=[describe(bars[max(0,i-79):i+1],spread=bars[i]['spread']*point) for i in range(n)]
            rows={}
            masks={}
            for hypothesis in hypotheses():
                key,base,gate=hypothesis['id'],hypothesis['base'],hypothesis['filter']
                mask=[allowed(gate,c,s) for c,s in zip(contexts,signals[base])]
                masks[key]=mask
                rows[key]={'definition':hypothesis,
                    'train':simulate(bars,signals[base],atr,61,a,point,entry_allowed=mask),
                    'validation':simulate(bars,signals[base],atr,a,b,point,entry_allowed=mask)}
            shortlist=sorted(rows,key=lambda key:rows[key]['train']['return_pct']-rows[key]['train']['drawdown_pct'],reverse=True)[:3]
            eligible=[key for key in shortlist if sufficient(rows[key]['train']) and sufficient(rows[key]['validation'])]
            chosen=max(eligible,key=lambda key:rows[key]['validation']['return_pct']-rows[key]['validation']['drawdown_pct']) if eligible else None
            registry=self.directory/'experiments.jsonl'
            previous=[json.loads(line) for line in registry.read_text().splitlines() if line] if registry.exists() else []
            overlap=any(r['scope']==scope and not (bars[-1]['time']<r['holdout_start'] or bars[b]['time']>r['holdout_end']) for r in previous)
            result={'version':VERSION,'experiment_id':ident,'scope':scope,'exit_policy_version':POLICY_VERSION,'data_sha256':hashlib.sha256(payload.encode()).hexdigest(),
                'status':'registered_before_holdout','candidate_before_holdout':chosen,
                'hypotheses_tested':len(rows),'experiments_registered':len(previous)+1,
                'holdout_start':bars[b]['time'],'holdout_end':bars[-1]['time'],
                'overlaps_previous_holdout':overlap,'independent_validation':False,
                'automatic_deployment':False,'volume_change':False,'split_indices':[a,b],
                'results':rows,'costs':'Historical bid OHLC/spread, 2 points slippage per side, 0.10R commission and 0.02R/day swap proxies; stress x1.5. Not broker-exact.',
                'note':'Historical screening only; prior use of these data cannot be ruled out. Future forward observation required.'}
            # Persist the fixed choice BEFORE inspecting any holdout. A crash cannot silently reselect.
            atomic(path,result)
            with registry.open('a') as audit:
                audit.write(json.dumps({k:result[k] for k in ('experiment_id','scope','candidate_before_holdout','holdout_start','holdout_end')})+'\n')
                audit.flush()
                import os
                os.fsync(audit.fileno())
            if not chosen:
                result['status']='no_candidate'
            elif overlap:
                result['status']='overlapping_holdout_not_retested'
            else:
                base=rows[chosen]['definition']['base']
                result['holdout']=simulate(bars,signals[base],atr,b,n,point,entry_allowed=masks[chosen])
                result['stress']=simulate(bars,signals[base],atr,b,n,point,1.5,entry_allowed=masks[chosen])
                result['baseline_holdout']=simulate(bars,signals[base],atr,b,n,point)
                passed=(sufficient(result['holdout'],20) and sufficient(result['stress'],20)
                    and result['holdout']['return_pct']>result['baseline_holdout']['return_pct']
                    and result['holdout']['drawdown_pct']<=result['baseline_holdout']['drawdown_pct'])
                result['status']='ready_for_forward_paper' if passed else 'failed_screening'
            atomic(path,result)
            atomic(self.directory/'latest.json',result)
            return result


def _book_step(book, bar, signal, atr, point, entry_ok):
    return step(book,bar,signal,atr,point,entry_ok=entry_ok)


class ForwardTrial:
    def __init__(self,path):
        self.path=Path(path)

    def observe(self,snapshot,experiment,now=None):
        now=time.time() if now is None else now
        bars=snapshot['bars']; point=snapshot['point']
        if experiment.get('status')!='ready_for_forward_paper':
            return {'status':'not_qualified_for_forward','automatic_deployment':False}
        if experiment['scope']!=[snapshot['login'],snapshot['symbol'],snapshot['period']]:
            raise ValueError('Forward trial account/symbol/timeframe mismatch')
        candidate=experiment['results'][experiment['candidate_before_holdout']]['definition']
        ident=experiment['experiment_id']
        state=json.loads(self.path.read_text()) if self.path.exists() else None
        if state and state.get('exit_policy_version')!=POLICY_VERSION:
            raise ValueError('Forward trial exit policy changed; start a versioned trial')
        if state and state['experiment_id']!=ident:
            raise ValueError('A forward trial cannot replace its frozen candidate')
        if state is None:
            book={'closed':0,'net_r':0.,'wins':0,'peak_r':0.,'drawdown_r':0.,'position':None}
            state={'exit_policy_version':POLICY_VERSION,'experiment_id':ident,'candidate':candidate,'scope':experiment['scope'],
                'cursor':bars[-1]['time'],'observed_utc':now,'started_utc':now,'gaps':0,
                'activation_after_bar':bars[-1]['time']+snapshot['period_seconds'],
                'baseline':dict(book),'challenger':dict(book),'automatic_deployment':False}
            atomic(self.path,state)
            return self.summary(state)
        unseen=[i for i,b in enumerate(bars) if b['time']>state['cursor']]
        if not unseen:
            return self.summary(state)
        continuous=(len(unseen)==1 and unseen[0]>0 and bars[unseen[0]-1]['time']==state['cursor']
            and 0<=now-state['observed_utc']<=snapshot['period_seconds']*2+120)
        if continuous:
            signals,atr=indicators(bars)
            i=unseen[0]; signal=signals[candidate['base']][i-1]
            context=describe(bars[max(0,i-80):i],spread=bars[i-1]['spread']*point)
            future=bars[i-1]['time']>=state['activation_after_bar']
            replay_bar={**bars[i],'period_seconds':snapshot['period_seconds']}
            _book_step(state['baseline'],replay_bar,signal,atr[i-1],point,future)
            _book_step(state['challenger'],replay_bar,signal,atr[i-1],point,future and allowed(candidate['filter'],context,signal))
        else:
            state['gaps']+=1
            state['activation_after_bar']=bars[-1]['time']+snapshot['period_seconds']
            # Interrupted exposure has an unknown result; it is never scored as a win.
            for key in ('baseline','challenger'):
                state[key]['position']=None
        state['cursor']=bars[-1]['time']; state['observed_utc']=now
        atomic(self.path,state)
        return self.summary(state)

    @staticmethod
    def summary(state):
        a,b=state['baseline'],state['challenger']
        enough=min(a['closed'],b['closed'])>=MIN_FORWARD_TRADES
        better=enough and b['net_r']>max(0,a['net_r']) and b['drawdown_r']<=a['drawdown_r'] and state['gaps']==0
        return {**state,'status':'candidate_for_review' if better else 'forward_observing',
            'minimum_closed_per_arm':MIN_FORWARD_TRADES,
            'note':'Paired future paper observation with proxy costs; never authorizes broker execution or more capital.'}
