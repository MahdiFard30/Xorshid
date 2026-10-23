"""Offline descriptive stop comparison. Never selects or deploys a winner."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ultimate_khorshid.tools.demo_lab import CATALOG,indicators,simulate,validate_bars


def run(output):
    output.mkdir(parents=True,exist_ok=True);symbols={}
    for symbol in ('XAUUSD','EURUSD','USDJPY'):
        choices=[]
        for folder in ('risk-upgrade-runtime','reports/20261021-120404'):
            p=ROOT/'local-backups'/folder/(symbol+'-snapshot.json')
            if p.exists():
                s=json.loads(p.read_text(encoding='utf-8-sig'))
                if len(s.get('bars',[]))>=1000:choices.append((s.get('generated_utc',0),p,s))
        if not choices:
            symbols[symbol]={'status':'insufficient_saved_data'};continue
        _,path,s=max(choices,key=lambda row:row[0]);bars=s['bars'];validate_bars(bars)
        signals,atr=indicators(bars);start=int(len(bars)*.8);rows={}
        for name,_,_ in CATALOG:
            rows[name]={str(stop):{'normal':simulate(bars,signals[name],atr,start,len(bars),s['point'],stop_atr=stop),
                'stress':simulate(bars,signals[name],atr,start,len(bars),s['point'],cost_multiplier=1.5,stop_atr=stop)} for stop in (1.,1.5,2.)}
        # Compare prefix calculations to the same prefix in the full computation.
        causal=[]
        for length in (100,500,1000):
            shorter,short_atr=indicators(bars[:length])
            causal.append(all(shorter[name]==values[:length] for name,values in signals.items()) and short_atr==atr[:length])
        record={'status':'descriptive_reused_data_only','source':str(path.relative_to(ROOT)),
            'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'candles':len(bars),
            'calendar_days':(bars[-1]['time']-bars[0]['time'])/86400,
            'period':s['period'],'period_seconds':s['period_seconds'],
            'matches_audit_timeframe':s['period']==json.loads((ROOT/'.khorshid-multi'/symbol/'state.json').read_text())['period'],
            'evaluation_start_server':bars[start]['time'],'evaluation_end_server':bars[-1]['time'],
            'prefix_causality_checks_passed':all(causal),'results':rows}
        symbols[symbol]=record
        print(symbol,'days',round(record['calendar_days'],1),'prefix checks',all(causal))
    result={'schema':1,'status':'not_ready_for_execution','automatic_deployment':False,
        'fixed_hypotheses_before_comparison':[1,1.5,2],'selected':None,
        'risk_fraction':.0025,'quick_target_r':1.,'news_mode':'historical_news_unavailable_quick_only',
        'limitations':['Archived OHLC was already used for research; this is not independent holdout evidence.',
            'All strategies and all three stop hypotheses reported; no winner is selected.',
            'Proxy costs and fractional lots; no broker-exact tick replay or portfolio/additional-position model.',
            'Indicator prefix checks address future-data leakage, not profitability or tick execution accuracy.',
            '90-day historical coverage and new multi-week forward-paper observations are still required.'],
        'symbols':symbols}
    (output/'stop-hypotheses.json').write_text(json.dumps(result,indent=2,allow_nan=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'reports/trading-audit/20261022')
    run(parser.parse_args().output)
