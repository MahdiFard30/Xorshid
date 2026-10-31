"""Offline chronological comparison. No terminal, order, network or approval writes.

Train paper scores on the first 60%, then evaluate on the final 40%.
Frozen evaluation never updates scores or attempts from evaluation results.
Walk-forward evaluation updates only after a candle's decision and outcome.
All fixed baselines are reported. This is an OHLC/proxy-cost diagnostic, not an
independent profitability certificate, and does not model portfolio allocation.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ultimate_khorshid.tools.demo_lab import indicators,simulate,CATALOG
from ultimate_khorshid.tools.demo_learning import Experience
from ultimate_khorshid.tools.execution_model import new_book,step,metrics
from ultimate_khorshid.tools.trading_controls import read
from ultimate_khorshid.tools.execution_policy import fingerprint

def validate(snapshot):
    bars=snapshot['bars'];period=snapshot['period_seconds']
    if not isinstance(period,(int,float)) or not math.isfinite(period) or period<=0:
        raise ValueError('Invalid candle period')
    point=snapshot['point']
    if not isinstance(point,(int,float)) or not math.isfinite(point) or point<=0:
        raise ValueError('Invalid price point')
    previous=None;gaps=0
    for i,b in enumerate(bars):
        for key in ('time','open','high','low','close','spread'):
            value=b.get(key)
            if not isinstance(value,(int,float)) or isinstance(value,bool) or not math.isfinite(value):
                raise ValueError(f'Invalid candle {i}: {key}')
        if b['time']<=0 or b['low']<=0 or not b['low']<=min(b['open'],b['close'])<=max(b['open'],b['close'])<=b['high'] or b['spread']<0:
            raise ValueError(f'Invalid candle {i}: OHLC/time/spread')
        if previous is not None:
            delta=b['time']-previous
            if delta<period or delta%period:
                raise ValueError(f'Invalid candle {i}: duplicate, unordered or overlapping time')
            gaps+=int(delta>period)
        previous=b['time']
    return {'ohlc_and_time_valid':True,'gap_count':gaps,
            'independent_feed_verified':False}


def compare(snapshot,controls,split=.6,mode='frozen',cost_multiplier=1.):
    bars=snapshot['bars'];point=snapshot['point'];period=snapshot['period_seconds']
    if len(bars)<1000:raise ValueError('At least 1000 closed candles required')
    if not .3<=split<=.8:raise ValueError('Split must be between .3 and .8')
    if mode not in ('frozen','walk_forward'):raise ValueError('Unknown evaluation mode')
    if not math.isfinite(cost_multiplier) or cost_multiplier<=0:raise ValueError('Invalid cost multiplier')
    quality=validate(snapshot)
    signals,atr=indicators(bars);start=int(len(bars)*split)
    names=[n for n,_,_ in CATALOG if n!='macd']
    with tempfile.TemporaryDirectory() as temp:
        learner=Experience(Path(temp)/'offline.json');learner.set_regime('offline-diagnostic-v3')
        books={name:new_book() for name in names};adaptive=new_book();held=None;entries=[]
        for i in range(61,len(bars)):
            bar={**bars[i],'period_seconds':period}
            previous={name:[signals[name][i-1]] for name in names}
            # Selection always precedes access to the current candle's outcome.
            selection=learner.rank(previous,allowed=names)
            if i>=start:
                chosen=selection['selected'];name=held if adaptive['position'] else chosen
                was_open=adaptive['position'] is not None
                events=step(adaptive,bar,signals[name][i-1] if name else 0,atr[i-1],point,
                    risk_fraction=.0025*(selection['risk_multiplier'] if not was_open and chosen else 1),
                    allow_entry=chosen is not None,controls=controls,cost_multiplier=cost_multiplier)
                for event in events:
                    if event['kind']=='open':
                        held=chosen
                        if mode=='walk_forward':learner.attempted(chosen)
                        entries.append({'bar':bar['time'],'strategy':chosen,'stage':selection['selection_stage']})
                if adaptive['position'] is None:held=None
            if i<start or mode=='walk_forward':
                for name in names:
                    for event in step(books[name],bar,signals[name][i-1],atr[i-1],point,controls=controls,cost_multiplier=cost_multiplier):
                        if event['kind']=='close':learner.reward(name,'paper',event['r'])
        if adaptive['position']:
            step(adaptive,{**bars[-1],'period_seconds':period},0,0,point,force_close=True,controls=controls,cost_multiplier=cost_multiplier)
        fixed={name:simulate(bars,signals[name],atr,start,len(bars),point,controls=controls,cost_multiplier=cost_multiplier) for name in names}
        return {'schema':1,'automatic_deployment':False,'validation_status':'diagnostic_only',
            'scope':{'symbol':snapshot.get('symbol'),'period_seconds':period},
            'bars':len(bars),'evaluation_mode':mode,'cost_multiplier':cost_multiplier,'data_quality':quality,
            'evaluation_start':bars[start]['time'],'evaluation_end':bars[-1]['time'],
            'effective_controls':controls,'adaptive':metrics(adaptive),'fixed_baselines':fixed,
            'adaptive_entries':entries,'limitations':[
                'OHLC with proxy spread/commission/slippage/swap; not broker tick replay.',
                'Adaptive diagnostics learn paper outcomes only, not historical fill rewards.',
                'No shared three-symbol budget, news schedule, native lot rounding or outage model.',
                'Fixed baselines use 0.25% risk; adaptive probation uses 25% of that amount.',
                'Dollar return alone is not a fair risk-normalized comparison; report net R and drawdown too.',
                'Reading this result spends the holdout; do not repeatedly tune against it.']}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=('frozen','walk_forward'),default='frozen')
    p.add_argument('--cost-multiplier',type=float,default=1.)
    a=p.parse_args();raw=a.snapshot.read_bytes();snapshot=json.loads(raw.decode('utf-8-sig'))
    result=compare(snapshot,read(ROOT),mode=a.mode,cost_multiplier=a.cost_multiplier);result.update(data_sha256=hashlib.sha256(raw).hexdigest(),source_sha256=fingerprint(ROOT))
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'output':str(a.output),'adaptive':result['adaptive'],'status':result['validation_status']},indent=2))
if __name__=='__main__':main()
