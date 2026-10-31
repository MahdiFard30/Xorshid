"""Auditable adaptive DEMO selection, not a calibrated profitability predictor.

Small samples may trade at 25% of the existing allocation. Sustained negative
execution evidence cannot be hidden by older paper profits. Recovery requires
20 new shadow closes after the last verified result; no real-account support.
"""
import math
from statistics import mean, stdev

WINDOW=60
MIN_DEMO=8
RETEST_PAPER=20

def ensure_windows(stats):
    for kind in ('paper','verified_demo'):
        key=kind+'_window'
        if not isinstance(stats.get(key),list):stats[key]=[]

def summary(rows):
    values=[r['r'] for r in rows if isinstance(r,dict) and type(r.get('r')) in (int,float) and math.isfinite(r['r'])]
    n=len(values);avg=mean(values) if n else 0.
    # Conservative floor prevents identical tiny samples implying zero uncertainty.
    se=max(stdev(values) if n>1 else 1.,.5)/math.sqrt(n) if n else None
    return {'n':n,'mean_r':avg,'se_heuristic':se,
            'upper_r_heuristic':avg+1.96*se if se is not None else None,
            'lower_r_heuristic':avg-1.96*se if se is not None else None}

def assess(stats):
    paper_rows=stats.get('paper_window',[]);demo_rows=stats.get('verified_demo_window',[])
    paper_rows=paper_rows if isinstance(paper_rows,list) else []
    demo_rows=demo_rows if isinstance(demo_rows,list) else []
    p=summary(paper_rows[-WINDOW:]);d=summary(demo_rows[-WINDOW:])
    # Legacy averages remain in reporting but do not stand in for scoped v3 samples.
    pn=min(p['n'],20);dn=3*min(d['n'],20)
    score=(pn*p['mean_r']+dn*d['mean_r'])/(pn+dn) if pn+dn else 0.
    if d['n']>=MIN_DEMO:score=d['mean_r']
    demo_bad=d['n']>=MIN_DEMO and (d['mean_r']<=-.25 or d['upper_r_heuristic']<0)
    paper_bad=d['n']<MIN_DEMO and p['n']>=20 and p['upper_r_heuristic']<0
    last_demo=max((r.get('utc',0) for r in demo_rows),default=0)
    fresh=summary([r for r in paper_rows if r.get('utc',0)>last_demo][-RETEST_PAPER:])
    recovery=demo_bad and fresh['n']>=RETEST_PAPER and fresh['lower_r_heuristic']>0
    eligible=not (demo_bad or paper_bad) or recovery
    stage=('shadow_retrial' if recovery else 'quarantined' if not eligible else
           'probation' if d['n']<MIN_DEMO or d['mean_r']<=0 else 'adaptive_demo')
    multiplier=0. if not eligible else .25 if stage in ('probation','shadow_retrial') else 1.
    recent=summary(demo_rows[-5:])
    strength=0.
    if multiplier==1.:
        edge=max(0.,min(d['mean_r'],recent['mean_r']))
        strength=min(1.,edge/d['se_heuristic']) if d['se_heuristic'] else 0.
        multiplier=.25+.75*strength
    return {'eligible':eligible,'stage':stage,'risk_multiplier':multiplier,
            'recent_demo':recent,'sizing_strength':strength,'sizing_policy':'gradual_recent_v1',
            'evidence_score':max(-3.,min(3.,score)), 'paper':p,'demo':d,'fresh_shadow':fresh,
            'demo_veto':demo_bad,'paper_veto':paper_bad,
            'reason':'fresh shadow evidence permits reduced-risk retest' if recovery else stage,
            'statistical_claim':'Operational heuristic; dependent trades and multiple testing are not corrected here'}
