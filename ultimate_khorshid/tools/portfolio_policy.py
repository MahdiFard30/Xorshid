"""Bounded three-symbol demo risk allocation. All values are equity fractions.

These are risk-at-stop estimates, not notional capital allocations. No hedge
credit, no Martingale, and no increase above the user-selected per-entry/symbol caps.
"""
import math
from statistics import mean
from ultimate_khorshid.tools.managed_exits import opportunity, SIZING_SCALE
from ultimate_khorshid.tools.exit_rules import POLICY_VERSION, outcome_policy
from ultimate_khorshid.tools.entry_protections import assess as protection_assessment
from ultimate_khorshid.tools.position_scaling import assess as scaling_assessment

SYMBOLS=('XAUUSD','EURUSD','USDJPY')
ENTRY_CAP=.005
SYMBOL_CAP=.005
PORTFOLIO_CAP=.005
USD_SIDE_CAP=.005
NEW_ENTRY_POOL=.005


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def usd_side(symbol,direction):
    return direction if symbol=='USDJPY' else -direction


def correlation(a,b,period_a=0,period_b=0):
    # Align completed candle ends first, then compute returns over identical spans.
    x={bar['time']+period_a:bar['close'] for bar in a}
    y={bar['time']+period_b:bar['close'] for bar in b}
    common=sorted(x.keys() & y.keys())[-97:]
    times=common[1:]
    if len(times)<40:
        return {'samples':len(times),'value':None}
    xs=[math.log(x[t]/x[previous]) for previous,t in zip(common,common[1:])]
    ys=[math.log(y[t]/y[previous]) for previous,t in zip(common,common[1:])]
    mx,my=mean(xs),mean(ys)
    divisor=math.sqrt(sum((v-mx)**2 for v in xs)*sum((v-my)**2 for v in ys))
    value=sum((u-mx)*(v-my) for u,v in zip(xs,ys))/divisor if divisor>0 else None
    return {'samples':len(times),'value':max(-1.,min(1.,value)) if value is not None else None}


def quality(outcomes):
    ordered=sorted(outcomes.values(),key=lambda g:g.get('closed_time_server') or 0)
    values=[max(-3.,min(3.,g['normalized_reward'])) for g in ordered
            if g.get('learning_eligible') is True and g.get('closed_complete') is True
            and outcome_policy(g)==POLICY_VERSION
            and finite(g.get('normalized_reward'))]
    values=values[-100:]
    n=len(values)
    average=mean(values) if n else 0.
    se=math.sqrt(sum((v-average)**2 for v in values)/(n-1)/n) if n>1 else None
    lower=average-1.96*se if se is not None else None
    score=1+max(-.75,min(.5,lower))*min(1,n/50) if n>=20 else 1.
    return {'verified_samples':n,'mean_r':average,'lower_mean_r_heuristic':lower,'score':score,
            'status':'evidence_weighted' if n>=20 else 'insufficient_evidence_neutral_weight'}


def allocate(snapshots,candidates,outcomes,news_factors,now,news_analyses=None):
    controls=next(iter(snapshots.values()),{}).get('trading_controls',{})
    gross=controls.get('portfolio_cap_fraction',PORTFOLIO_CAP)
    base={'version':1,'updated_utc':now,'expires_utc':now+15,'mode':'advisory',
          'entry_cap_fraction':ENTRY_CAP,'symbol_cap_fraction':SYMBOL_CAP,
          'portfolio_cap_fraction':gross,'usd_side_cap_fraction':gross,
          'budget_basis':'reference_before_tighter_stop_scaling','execution_risk_scale':SIZING_SCALE,
          'execution_entry_cap_fraction':ENTRY_CAP*SIZING_SCALE,
          'automatic_cap_increase':False}
    try:
        if set(snapshots)!=set(SYMBOLS):
            raise ValueError('All three fresh chart snapshots required')
        scopes=set()
        for symbol,s in snapshots.items():
            if (s.get('demo') is not True or s.get('connected') is not True or s.get('symbol')!=symbol
                    or not finite(s.get('generated_utc')) or not -5<=now-s['generated_utc']<=15
                    or not finite(s.get('equity')) or s['equity']<=0):
                raise ValueError('Stale, invalid or non-demo snapshot: '+symbol)
            if len(s.get('bars',[]))<2 or any(not finite(b.get('close')) or b['close']<=0 for b in s['bars']):
                raise ValueError('Invalid correlation price history: '+symbol)
            if not finite(s.get('period_seconds')) or not 0<s['period_seconds']<=86400:
                raise ValueError('Invalid chart timeframe')
            scopes.add((s['login'],s['currency']))
        if len(scopes)!=1:
            raise ValueError('Account/currency mismatch')
        equities=[s['equity'] for s in snapshots.values()]
        if max(equities)/min(equities)>1.01:
            raise ValueError('Inconsistent account equity snapshots')
    except (ValueError,KeyError) as exc:
        return {**base,'status':'allocation_unavailable','reason':str(exc),'execution_ready':False,'symbols':{}}
    equity=min(equities)
    used={s:0. for s in SYMBOLS}; usd_used={-1:0.,1:0.}; risk_known=True
    all_modern=all(s.get('executor_version')==9 and s.get('exit_policy_version')==POLICY_VERSION and s.get('adaptive_risk_schema')==1 and s.get('risk_policy_version')==2 for s in snapshots.values())
    for symbol,s in snapshots.items():
        for p in s.get('positions',[]):
            risk=p.get('sl_risk_cash')
            if not finite(risk) or risk<0 or type(p.get('direction')) is not int or p['direction'] not in (-1,1):
                risk_known=False;continue
            used[symbol]+=risk/equity
            usd_used[usd_side(symbol,p['direction'])]+=risk/equity
    qs={s:quality({k:g for k,g in outcomes.get(s,{}).items()
                  if g.get('account')==snapshots[s]['login'] and g.get('symbol')==s}) for s in SYMBOLS}
    opportunities={s:opportunity((news_analyses or {}).get(s,{}),candidates.get(s,{}).get('direction'),
                                now,snapshots[s]['period_seconds']) for s in SYMBOLS}
    scaling={s:scaling_assessment(snapshots[s],candidates.get(s,{}),qs[s],opportunities[s]) for s in SYMBOLS}
    scores={s:qs[s]['score']*opportunities[s]['weight_multiplier'] for s in SYMBOLS}
    weights={s:scores[s]/sum(scores.values()) for s in SYMBOLS}
    all_outcomes={f'{symbol}:{ident}':o for symbol,groups in outcomes.items() for ident,o in groups.items()}
    global_guard=protection_assessment(snapshots[SYMBOLS[0]],all_outcomes,global_scope=True)
    account_guards={s:protection_assessment(snapshot,all_outcomes,global_scope=True) for s,snapshot in snapshots.items()}
    guards={s:protection_assessment(snapshots[s],outcomes.get(s,{})) for s in SYMBOLS}
    correlations={}
    penalties={s:1. for s in SYMBOLS}
    for i,a in enumerate(SYMBOLS):
        for b in SYMBOLS[i+1:]:
            corr=correlation(snapshots[a]['bars'],snapshots[b]['bars'],snapshots[a]['period_seconds'],snapshots[b]['period_seconds'])
            correlations[a+':'+b]=corr
            da,db=candidates.get(a,{}).get('direction',0),candidates.get(b,{}).get('direction',0)
            if da in (-1,1) and db in (-1,1):
                same_risk=(corr['value'] is not None and corr['value']*da*db>=.7)
                unknown_same_usd=corr['value'] is None and usd_side(a,da)==usd_side(b,db)
                if same_risk or unknown_same_usd:
                    penalties[a]=min(penalties[a],.5);penalties[b]=min(penalties[b],.5)
    eligible=[]
    for symbol,s in snapshots.items():
        c=candidates.get(symbol,{})
        factor=news_factors.get(symbol,0.)
        if (type(c.get('direction')) is int and c['direction'] in (-1,1)
                and scaling[symbol]['allow_entry']
                and account_guards[symbol]['allow_entry'] and guards[symbol]['allow_entry']
                and finite(factor) and 0<factor<=1 and c.get('strategy')
                and s.get('algo_enabled') is True and not s.get('halted') and not s.get('stopped')
                and s.get('weekly_schedule_known') is True and not s.get('weekly_close_paused')
                and s.get('blocking_positions')==0 and s.get('total_orders')==0
                and len(s.get('positions',[]))<s.get('max_positions',0)
                and all(p.get('direction')==c['direction'] for p in s.get('positions',[]))
                and finite(s.get('bar_age_seconds')) and 0<=s['bar_age_seconds']<=s.get('entry_window_seconds',0)
                and finite(s.get('tick_age_seconds')) and 0<=s['tick_age_seconds']<=120):
            eligible.append(symbol)
    total_available=max(0.,min(NEW_ENTRY_POOL,gross-sum(used.values()))) if risk_known else 0.
    shares={s:scores[s]/sum(scores[k] for k in eligible) for s in eligible}
    rows={}
    for symbol,s in snapshots.items():
        c=candidates.get(symbol,{}); direction=c.get('direction',0)
        cap=min(SYMBOL_CAP,gross*weights[symbol])
        proposed=min(ENTRY_CAP,total_available*shares.get(symbol,0),max(0.,cap-used[symbol]))
        if direction in (-1,1):
            members=[k for k in eligible if usd_side(k,candidates[k]['direction'])==usd_side(symbol,direction)]
            side_share=scores[symbol]/sum(scores[k] for k in members) if symbol in members else 0.
            proposed=min(proposed,max(0.,gross-usd_used[usd_side(symbol,direction)])*side_share)
        else:
            proposed=0.
        factor=news_factors.get(symbol,0)
        factor=factor if finite(factor) and 0<=factor<=1 else 0.
        proposed*=factor*penalties[symbol]
        # Rounded down, never rounded up through a safety ceiling.
        proposed=math.floor(max(0,proposed)*1e10)/1e10
        rows[symbol]={'weight':weights[symbol],'quality':qs[symbol],'opportunity':opportunities[symbol],'position_scaling':scaling[symbol],'entry_protection':guards[symbol],'account_entry_protection':account_guards[symbol],'strategy':c.get('strategy'),
            'direction':direction,'signal_bar':s['bars'][-1]['time'],'period':s['period'],
            'executor_instance':s.get('executor_instance'),'used_risk_fraction':used[symbol] if risk_known else None,
            'symbol_budget_fraction':cap,'entry_budget_fraction':proposed,'entry_risk_pct':proposed*100,
            'execution_entry_budget_fraction':math.floor(proposed*SIZING_SCALE*1e10)/1e10,
            'news_risk_factor':factor,'correlation_risk_factor':penalties[symbol],
            'reason':'eligible_bounded_allocation' if proposed else 'no_eligible_entry_or_no_risk_headroom'}
    return {**base,'account':snapshots[SYMBOLS[0]]['login'],'currency':snapshots[SYMBOLS[0]]['currency'],
            'status':'ready' if all_modern and risk_known else 'pending_executor_upgrade_or_risk_evidence',
            'account_entry_protection':global_guard,'exit_policy_version':POLICY_VERSION,
            'execution_ready':all_modern and risk_known,'symbols':rows,'correlations':correlations,
            'equity_reference':equity,'open_risk_fraction':sum(used.values()) if risk_known else None,
            'note':'Risk-at-stop estimates exclude gap/slippage guarantees. Missing history keeps weights neutral; correlated and news-conflicting entries are reduced.'}


def constrain(plan,snapshot,advice,now):
    if plan.get('action')!='open':
        return plan
    row=advice.get('symbols',{}).get(snapshot['symbol'],{})
    valid=(advice.get('execution_ready') is True and advice.get('version')==1
           and advice.get('account')==snapshot['login'] and advice.get('currency')==snapshot['currency']
           and finite(advice.get('updated_utc')) and finite(advice.get('expires_utc'))
           and -5<=now-advice['updated_utc']<=15 and now<=advice['expires_utc']<=advice['updated_utc']+15
           and row.get('period')==snapshot['period'] and row.get('signal_bar')==snapshot['bars'][-1]['time']
           and row.get('executor_instance')==snapshot.get('executor_instance')
           and row.get('strategy')==plan.get('strategy') and row.get('direction')==plan.get('direction')
           and snapshot.get('executor_version')==9 and snapshot.get('exit_policy_version')==POLICY_VERSION and snapshot.get('adaptive_risk_schema')==1 and snapshot.get('risk_policy_version')==2)
    entry,cap=row.get('entry_budget_fraction'),row.get('symbol_budget_fraction')
    if not valid or not finite(entry) or not 0<entry<=ENTRY_CAP or not finite(cap) or not entry<=cap<=SYMBOL_CAP:
        return {'status':'waiting_for_portfolio_allocation','reason':'Fresh matching bounded portfolio allocation unavailable'}
    return {**plan,'risk_fraction':entry,'symbol_cap_fraction':cap,
            'portfolio_allocation_utc':advice['updated_utc']}
