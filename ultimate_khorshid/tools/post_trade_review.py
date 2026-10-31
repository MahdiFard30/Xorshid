"""Evidence-based post-trade reports. Never used by execution or scoring.

Facts, possible contributing factors and unknown causes are kept separate.
The source journals are opened read-only; reviews use a separate append-only DB.
"""
from collections import Counter, defaultdict
import fcntl
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from ultimate_khorshid.tools.trade_memory import TradeMemory

VERSION=1
ANALYZER_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
SYMBOLS=('XAUUSD','EURUSD','USDJPY')


def ensure_started(root):
    """Start only the independent reporter; singleton prevents duplicate writers."""
    root=Path(root);directory=root/'.khorshid-research/post-trade';directory.mkdir(parents=True,exist_ok=True)
    with (directory/'watcher.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:return {'status':'already_running'}
        fcntl.flock(lock,fcntl.LOCK_UN)
    with (directory/'watcher.log').open('ab') as log:
        process=subprocess.Popen([sys.executable,str(root/'scripts/review_trade_outcomes.py'),'--watch'],
                                 cwd=root,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
    return {'status':'starting','pid':process.pid}


def finite(value):
    return type(value) in (int,float) and math.isfinite(value)


def encoded(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False)


def review(outcome,deals,period):
    """Interpret recorded evidence only; no post-hoc entry thesis generation."""
    contexts=outcome.get('entry_contexts',[])
    ctx=contexts[0] if len(contexts)==1 else {}
    decision=ctx.get('decision',{})
    plan=decision.get('plan',{})
    details=decision.get('learning',{}).get('score_details',{}).get(outcome['strategy'],{})
    market=decision.get('market_context') or {}
    entries=[d for d in deals if d.get('entry')==0]
    entry=entries[0] if len(entries)==1 else {}
    risk_record=entry.get('initial_risk') or {}
    captured=risk_record.get('captured_utc');recorded=ctx.get('recorded_utc')
    timely=(outcome.get('learning_eligible') is True and finite(captured)
            and finite(recorded) and 0<recorded<captured+1)
    # Native timestamps are second-resolution. Late/missing evidence is retained
    # but cannot support a claim about what was known before entry.
    gaps=list(outcome.get('evidence_problems',[]))
    if not ctx:gaps.append('missing_or_multiple_entry_contexts')
    if not timely:gaps.append('entry_evidence_timing_unverified')
    factors=[]
    def factor(label,evidence):
        factors.append({'label':label,'assessment':'possible_contributing_factor',
                        'causal_proof':False,'evidence':evidence})
    if timely:
        evidence=details.get('evidence_before_exploration');evidence_source='recorded_entry_score'
        if evidence is None and finite(details.get('experience_score')) and finite(details.get('context_adjustment')):
            evidence=details['experience_score']+details['context_adjustment']
            evidence_source='reconstructed_from_recorded_components; original precision may be limited'
        if finite(evidence) and evidence<0:
            factor('negative_entry_evidence',{'value':evidence,'source':evidence_source})
        context_adjustment=details.get('context_adjustment')
        if finite(context_adjustment) and context_adjustment<0:
            factor('adverse_similar_market_history',{'context_adjustment':context_adjustment})
        side=ctx.get('direction')
        if (market.get('trend'),side) in (('up',-1),('down',1)):
            factor('entry_against_recorded_trend',{'trend':market['trend'],'direction':side,
                    'caution':'Reversal strategies may intentionally trade against a trend.'})
        n=details.get('demo_results');multiplier=details.get('risk_multiplier')
        if finite(n) and n<20 and multiplier==1:
            factor('full_allocation_with_limited_demo_history',{'prior_demo_results':n,
                    'risk_multiplier':multiplier,'caution':'Describes loss magnitude exposure, not direction accuracy; 20 is a reporting heuristic.'})
    costs={k:outcome.get(k) for k in ('commission','fee','swap')}
    known_costs=all(finite(v) for v in costs.values())
    cost_drag=-sum(min(0,v) for v in costs.values()) if known_costs else None
    risk=outcome.get('risk_cash')
    cost_r=cost_drag/risk if cost_drag is not None and finite(risk) and risk>0 else None
    if cost_r is not None and cost_r>=.1:
        factor('explicit_cost_drag',{'costs':costs,'cost_drag_r':cost_r,
                                   'caution':'Does not include a separate estimate of embedded spread/slippage.'})
    execution={}
    distance=ctx.get('sl_distance_requested');side=ctx.get('direction')
    quote=ctx.get('ask') if side==1 else ctx.get('bid')
    if timely and side in (-1,1) and all(finite(v) and v>0 for v in (quote,entry.get('price'),distance)):
        adverse=side*(entry['price']-quote)/distance
        execution['adverse_fill_vs_request_r']=adverse
        if adverse>=.1:
            factor('adverse_fill_vs_recorded_request',{'distance_r':adverse,
                    'caution':'Includes intervening market movement; not proof of broker slippage.'})
    bid,ask=ctx.get('bid'),ctx.get('ask')
    if finite(bid) and finite(ask) and bid>0 and ask>=bid and finite(distance) and distance>0:
        execution['entry_spread_to_stop_distance']=(ask-bid)/distance
    else:gaps.append('entry_quote_or_stop_distance_unavailable_or_invalid')
    path=outcome.get('observed_path') or {}
    # Legacy samples can contain bogus huge P/L. Preserve them, never use them
    # to recommend an exit or claim that an alternative exit would have won.
    excursions={k:path.get(k) for k in ('samples','min_floating_profit','max_floating_profit','min_progress_r','max_progress_r','coverage')}
    if any(finite(path.get(k)) and abs(path[k])>100 for k in ('min_progress_r','max_progress_r')):
        gaps.append('implausible_excursion_samples_unverified')
    gaps.extend(['tick_path_not_complete','independent_feed_not_verified',
                 'breakout_level_and_reentry_path_not_verified','late_entry_counterfactual_not_tested',
                 'alternative_exit_not_tested'])
    complete=outcome.get('closed_complete') is True
    net=outcome.get('net')
    result=('open_or_incomplete' if not complete else
            'loss' if finite(net) and net<0 else 'win' if finite(net) and net>0 else
            'breakeven' if finite(net) else 'unknown')
    return {'schema':VERSION,'analyzer_source_sha256':ANALYZER_SOURCE_SHA256,
            'scope':{'account':outcome['account'],'symbol':outcome['symbol'],
                'period':period,'position_id':str(outcome['position_id']),
                'strategy':outcome['strategy'],'learning_regime':outcome.get('learning_regime'),
                'environment':'executed_demo',
                'code_revisions':outcome.get('code_revisions',[])},
            'result':result,'assessment_status':'provisional' if complete else 'not_a_completed_trade',
            'exact_cause':'undetermined','report_only':True,'affects_scoring':False,
            'facts':{'net':net,'risk_cash':risk,'normalized_reward':outcome.get('normalized_reward'),
                'explicit_costs':costs,'exit_reasons':outcome.get('exit_reasons',[]),
                'closed_time_server':outcome.get('closed_time_server'),'deal_tickets':outcome.get('deal_tickets',[]),
                'execution':execution,'observed_excursions':excursions},
            'entry_evidence':{'source':'original_order_intent','request_id':ctx.get('request_id'),
                'recorded_utc':recorded,'timing_verified_to_seconds':timely,
                'direction':ctx.get('direction'),
                'recorded_reason':plan.get('reason'),'entry_plan':plan,'market_context':market,
                'score_details':details,'news':ctx.get('news'),
                'limitation':'Generic entry reasons are not a detailed precommitted market thesis.'},
            'possible_factors':factors if complete else [],'evidence_gaps':sorted(set(gaps)),
            'interpretation':'A loss does not prove an entry error; a win does not validate a strategy.'}


class ReviewStore:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with sqlite3.connect(self.path) as con:
            con.execute('''CREATE TABLE IF NOT EXISTS reviews(
                id INTEGER PRIMARY KEY,identity TEXT,sha256 TEXT,recorded_utc REAL,data TEXT,
                UNIQUE(identity,sha256))''')
            con.execute('CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,recorded_utc REAL,data TEXT)')
            con.execute('''CREATE TABLE IF NOT EXISTS observations(
                identity TEXT,utc REAL,sha256 TEXT,data TEXT,UNIQUE(identity,utc,sha256))''')
    def append(self,report):
        raw=encoded(report);digest=hashlib.sha256(raw.encode()).hexdigest()
        s=report['scope'];identity=encoded([s['account'],s['symbol'],s['period'],s['position_id'],VERSION])
        with sqlite3.connect(self.path,timeout=5) as con:
            cur=con.execute('INSERT OR IGNORE INTO reviews(identity,sha256,recorded_utc,data) VALUES(?,?,?,?)',
                            (identity,digest,time.time(),raw))
            return cur.rowcount==1
    def record_run(self,summary):
        with sqlite3.connect(self.path,timeout=5) as con:
            con.execute('INSERT INTO runs(recorded_utc,data) VALUES(?,?)',(time.time(),encoded(summary)))
    def capture(self,snapshot):
        """Prospective partial path, including invalid samples with quality flags."""
        if not -5<=time.time()-snapshot.get('generated_utc',0)<=15:return
        for position in snapshot.get('positions',[]):
            scope=[snapshot['login'],snapshot['symbol'],snapshot['period'],str(position['identifier'])]
            sample={k:snapshot.get(k) for k in ('generated_utc','connected','account_data_valid',
                'account_data_note','bid','ask','tick_age_seconds','broker_utc_offset_seconds')}
            sample.update(position=position,recent_closed_bars=snapshot.get('bars',[])[-21:],
                          coverage='periodic snapshots, not complete tick replay')
            raw=encoded(sample)
            with sqlite3.connect(self.path,timeout=5) as con:
                con.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?,?)',
                    (encoded(scope),snapshot['generated_utc'],hashlib.sha256(raw.encode()).hexdigest(),raw))


def collect(root,terminal,store):
    """Read journals and terminal snapshots; write only the separate review store."""
    root=Path(root);terminal=Path(terminal);reports=[];errors={};added=0
    for symbol in SYMBOLS:
        try:
            snapshot=json.loads((terminal/'MQL5/Files/khorshid_multi'/symbol/'khorshid_demo_snapshot.json').read_text(encoding='utf-8-sig'))
            state=json.loads((root/'.khorshid-multi'/symbol/'state.json').read_text())
            if (snapshot.get('demo') is not True or snapshot.get('symbol')!=symbol
                    or snapshot.get('login')!=state.get('login') or snapshot.get('period')!=state.get('period')):
                raise ValueError('Demo/account/symbol/timeframe scope mismatch')
            store.capture(snapshot)
            memory=TradeMemory.read_only(root/'.khorshid-multi'/symbol/'trade_memory.sqlite')
            groups=memory.outcomes(snapshot)
            with memory.connect() as con:
                deals=defaultdict(list)
                for (raw,) in con.execute('SELECT data FROM observations WHERE account=? AND symbol=?',(snapshot['login'],symbol)):
                    d=json.loads(raw);deals[str(d['position_id'])].append(d)
            for ident,outcome in groups.items():
                # Current-position state must be fresh to call a trade complete.
                age=time.time()-snapshot.get('generated_utc',0)
                if not -5<=age<=15:
                    outcome={**outcome,'closed_complete':False,
                             'evidence_problems':outcome.get('evidence_problems',[])+['stale_terminal_snapshot']}
                report=review(outcome,deals[ident],snapshot['period'] if outcome.get('entry_contexts') else None)
                added+=store.append(report);reports.append(report)
        except (OSError,ValueError,KeyError,TypeError,sqlite3.Error) as exc:
            errors[symbol]=type(exc).__name__+': '+str(exc)
    closed=[r for r in reports if r['assessment_status']=='provisional']
    patterns=defaultdict(list)
    for r in closed:
        s=r['scope'];context=r['entry_evidence']['market_context']
        for factor in r['possible_factors']:
            key=encoded([s['account'],s['symbol'],s['period'],s['learning_regime'],s['strategy'],
                         r['entry_evidence']['direction'],context.get('trend'),context.get('volatility'),
                         context.get('session'),context.get('spread_band'),factor['label']])
            patterns[key].append(r)
    return {'schema':VERSION,'updated_utc':time.time(),'report_only':True,'orders_sent':False,
            'new_revisions':added,'errors':errors,'reviewed_positions':len(reports),
            'results':dict(Counter(r['result'] for r in reports)),
            'patterns':[{'scope':json.loads(k),'n':len(v),'losses':sum(r['result']=='loss' for r in v),
                'net':sum(r['facts']['net'] for r in v) if all(finite(r['facts']['net']) for r in v) else None,
                'predictive_value':'not_yet_validated'} for k,v in patterns.items()],
            'reviews':reports,'limitation':'Descriptive, selected executed trades only; not causal attribution or independent validation.'}
