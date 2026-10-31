"""Deterministic, causal strategy screening; no downloaded code or LLM orders."""
import hashlib
import json
import math
from ultimate_khorshid.tools.exit_rules import STOP_ATR
from statistics import mean, pstdev

FID='https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/'
CATALOG=[
 ('sma_cross','SMA 20/50 crossover',FID+'sma'),
 ('ema_cross','EMA 12/26 crossover','https://www.fidelity.com/viewpoints/active-investor/moving-averages'),
 ('macd','MACD 12/26/9 crossover','https://www.fidelity.com/learning-center/trading-investing/technical-trading'),
 ('rsi_rebound','RSI 14 return through 30/70',FID),
 ('bollinger_reentry','Bollinger 20/2 band re-entry','https://www.fidelity.com/viewpoints/active-investor/bollinger-bands'),
 ('stochastic','Stochastic 14/3 cross near 20/80','https://www.fidelity.com/quick-content/etf/help/research/learn_er_glossary_4.shtml'),
 ('donchian','Donchian previous 20 bar breakout','https://www.ig.com/uk/trading-strategies/a-trader-s-guide-to-donchian-channels-200218'),
 ('roc','20 bar momentum zero cross',FID+'roc'),
 ('cci','CCI 20 return through -100/+100',FID+'cci'),
 ('trend_pullback','EMA 50 trend plus RSI 14 pullback','https://www.fidelity.com/quick-content/etf/help/research/learn_er_glossary_3.shtml')]
# Indicator sources are educational; the precise combined rules/risk settings are our test hypotheses.
VERSION='demo-lab-2.0'
RULES={'exit_policy_version':2,'stop_atr':1.0,'quick_target_r':1.0,'staged_targets_r':[1.0,2.0],'max_hold_bars':24,'risk_fraction':0.0025,
       'entry':'next bar open after closed-bar signal','exit':'current policy: SL, profile TP, partial/trailing, failed thesis, opposite signal or 24 bars',
       'ambiguous_bar':'old stop first; pessimistic trailing after partial; fractional-volume approximation','splits':'60% train, 20% validation, 20% holdout',
       'minimum_bars':1000,'minimum_validation_trades':5,'minimum_holdout_trades':5,
       'disclaimer':'Ten testable hypotheses, not the ten best strategies. Rolling holdout reuse is not independent proof.'}


def ema(xs,n):
    out=[]; v=xs[0]; a=2/(n+1)
    for x in xs: v+=a*(x-v); out.append(v)
    return out


def wilder(xs,n):
    out=[]; v=xs[0]
    for i,x in enumerate(xs):
        v=mean(xs[:i+1]) if i<n else (v*(n-1)+x)/n
        out.append(v)
    return out


def validate_bars(bars):
    if len(bars)<65: raise ValueError('At least 65 closed candles required')
    previous=-1
    for b in bars:
        if not all(isinstance(b.get(k),(float,int)) and math.isfinite(b[k]) for k in ('time','open','high','low','close','spread')):
            raise ValueError('Invalid OHLC/spread data')
        if b['time']<=previous or b['low']<=0 or b['high']<max(b['open'],b['close']) or b['low']>min(b['open'],b['close']) or b['spread']<0:
            raise ValueError('Unsorted or invalid candles')
        previous=b['time']


def indicators(bars):
    validate_bars(bars)
    c=[b['close'] for b in bars]; n=len(c)
    e12,e26,e50=ema(c,12),ema(c,26),ema(c,50)
    macd=[a-b for a,b in zip(e12,e26)]; sig=ema(macd,9)
    up=wilder([0]+[max(c[i]-c[i-1],0) for i in range(1,n)],14)
    down=wilder([0]+[max(c[i-1]-c[i],0) for i in range(1,n)],14)
    rsi=[100-100/(1+u/d) if d else (100 if u else 50) for u,d in zip(up,down)]
    tr=[max(b['high']-b['low'],abs(b['high']-c[max(0,i-1)]),abs(b['low']-c[max(0,i-1)])) for i,b in enumerate(bars)]
    atr=wilder(tr,14); sma20=[]; sma50=[]; upper=[]; lower=[]; k=[]; cci=[]; roc=[]
    typical=[(b['high']+b['low']+b['close'])/3 for b in bars]
    for i,b in enumerate(bars):
        w=c[max(0,i-19):i+1]; avg=mean(w); sd=pstdev(w)
        sma20.append(avg); sma50.append(mean(c[max(0,i-49):i+1])); upper.append(avg+2*sd); lower.append(avg-2*sd)
        chunk=bars[max(0,i-13):i+1]; hi=max(x['high'] for x in chunk); lo=min(x['low'] for x in chunk)
        k.append(100*(c[i]-lo)/(hi-lo) if hi>lo else 50)
        tp=typical[max(0,i-19):i+1]; av=mean(tp); dev=mean([abs(t-av) for t in tp])
        cci.append((typical[i]-av)/(.015*dev) if dev else 0)
        roc.append(c[i]/c[max(0,i-20)]-1)
    d=[mean(k[max(0,i-2):i+1]) for i in range(n)]
    result={name:[0]*n for name,_,_ in CATALOG}
    def cross(a,b,i): return 1 if a[i]>b[i] and a[i-1]<=b[i-1] else (-1 if a[i]<b[i] and a[i-1]>=b[i-1] else 0)
    zero=[0]*n
    for i in range(60,n):
        result['sma_cross'][i]=cross(sma20,sma50,i)
        result['ema_cross'][i]=cross(e12,e26,i)
        result['macd'][i]=cross(macd,sig,i)
        result['rsi_rebound'][i]=1 if rsi[i-1]<30<=rsi[i] else (-1 if rsi[i-1]>70>=rsi[i] else 0)
        result['bollinger_reentry'][i]=1 if c[i-1]<lower[i-1] and c[i]>=lower[i] else (-1 if c[i-1]>upper[i-1] and c[i]<=upper[i] else 0)
        st=cross(k,d,i)
        result['stochastic'][i]=st if (st==1 and min(k[i],k[i-1])<20) or (st==-1 and max(k[i],k[i-1])>80) else 0
        prev=bars[i-20:i]
        result['donchian'][i]=1 if c[i]>max(x['high'] for x in prev) else (-1 if c[i]<min(x['low'] for x in prev) else 0)
        result['roc'][i]=cross(roc,zero,i)
        result['cci'][i]=1 if cci[i-1]<-100<=cci[i] else (-1 if cci[i-1]>100>=cci[i] else 0)
        result['trend_pullback'][i]=1 if c[i]>e50[i] and rsi[i-1]<40<=rsi[i] else (-1 if c[i]<e50[i] and rsi[i-1]>60>=rsi[i] else 0)
    return result,atr


def simulate(bars,signals,atr,start,end,point,cost_multiplier=1.0,entry_allowed=None,entry_profiles=None,stop_atr=STOP_ATR,controls=None):
    """Current live exit policy with conservative OHLC ordering and proxy costs.

    Historical news profiles are quick unless supplied with pre-entry timestamps.
    """
    from ultimate_khorshid.tools.execution_model import new_book, step, metrics
    book=new_book()
    for i in range(max(start,61),end):
        bar={**bars[i],'period_seconds':bars[i]['time']-bars[i-1]['time']}
        profile=(entry_profiles or {}).get(bars[i-1]['time'])
        step(book,bar,signals[i-1],atr[i-1],point,
             entry_ok=entry_allowed is None or bool(entry_allowed[i-1]),
             cost_multiplier=cost_multiplier,profile=profile,stop_atr=stop_atr,controls=controls)
    if book['position'] is not None:
        step(book,bars[end-1],0,0,point,cost_multiplier=cost_multiplier,allow_entry=False,force_close=True,stop_atr=stop_atr,controls=controls)
    return metrics(book)


def qualifies(m):
    return m['trades']>=5 and m['return_pct']>0 and m['profit_factor']>=1.1 and m['drawdown_pct']<=10


def evaluate(bars,point,controls=None):
    if len(bars)<1000: raise ValueError(f'Need 1000 closed candles, have {len(bars)}; load chart history in MT5.')
    if not math.isfinite(point) or point<=0: raise ValueError('Invalid point size')
    signals,atr=indicators(bars); n=len(bars); a=int(n*.6); b=int(n*.8)
    rows={}
    for name,title,url in CATALOG:
        train=simulate(bars,signals[name],atr,61,a,point,controls=controls)
        valid=simulate(bars,signals[name],atr,a,b,point,controls=controls)
        rows[name]={'name':title,'source':url,'train':train,'validation':valid}
    shortlist=sorted(rows,key=lambda k:rows[k]['train']['return_pct']-rows[k]['train']['drawdown_pct'],reverse=True)[:3]
    eligible=[k for k in shortlist if qualifies(rows[k]['validation']) and rows[k]['train']['return_pct']>0]
    candidate=max(eligible,key=lambda k:rows[k]['validation']['return_pct']-rows[k]['validation']['drawdown_pct']) if eligible else None
    selected=None
    # All ten results retained for research; choice is fixed before any holdout is inspected.
    for name in rows:
        rows[name]['holdout']=simulate(bars,signals[name],atr,b,n,point,controls=controls)
        rows[name]['stress']=simulate(bars,signals[name],atr,b,n,point,1.5,controls=controls)
        rows[name]['profitable_holdout']=qualifies(rows[name]['holdout'])
    if candidate and qualifies(rows[candidate]['holdout']) and qualifies(rows[candidate]['stress']): selected=candidate
    return {'version':VERSION,'selected':selected,'candidate_before_holdout':candidate,'results':rows,'rules':RULES,'effective_controls':dict(controls or {}),
            'bars':n,'split_indices':[a,b],'first_bar':bars[0]['time'],'last_bar':bars[-1]['time'],
            'historical_news':'Unknown news uses quick profile; staged needs pre-entry timestamped evidence','data_sha256':hashlib.sha256(json.dumps(bars,sort_keys=True).encode()).hexdigest(),
            'costs':'Bid candles; historical spread (floor 2 points), 2 points slippage per side, 0.10R commission and 0.02R/day swap proxies; stress x1.5. Approximate, not broker-exact.',
            'reason':'passed screening' if selected else 'No candidate passed; no new trades.'}
