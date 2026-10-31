"""Fail-closed reviewed execution or explicitly authorized adaptive DEMO trials.

Research results never write approvals. Start and every open request independently
check scope, expiry, code fingerprint and a reviewed validation artifact.
"""
import hashlib
import json
from pathlib import Path
import time
from ultimate_khorshid.tools.exit_rules import POLICY_VERSION, finite
from ultimate_khorshid.tools.demo_lab import CATALOG

SOURCES=('demo_lab.py','execution_model.py','exit_rules.py','mt5_entry_policy.py',
         'managed_exits.py','portfolio_policy.py','position_scaling.py','execution_policy.py',
         'mt5_multi_worker.py','research_observer.py','headline_research.py','news_analysis.py',
         'trade_memory.py','market_learning.py','demo_learning.py','entry_protections.py',
         'mt5_recovery.py','mt5_news_calendar.py','news_grounding.py','trading_controls.py','history_archive.py','learning_evidence.py')


def fingerprint(root):
    digest=hashlib.sha256()
    for name in SOURCES:
        digest.update(name.encode());digest.update((root/'ultimate_khorshid/tools'/name).read_bytes())
    for name in ('KhorshidMultiTrader.mq5','RestartPolicy.mqh'):
        digest.update(name.encode());digest.update((root/'mt5'/name).read_bytes())
    return digest.hexdigest()


def learning_identity(row, controls):
    # Cosmetic config metadata does not alter the identity; every execution option does.
    effective={k:v for k,v in row.items() if k not in ('learning_regime','experiment_id',
        'learning_source_sha256','learning_source_for_sha256')}
    # Explicit, code-bound continuation preserves evidence for an approved reload.
    # Execution authorization still checks the actual source_sha256 independently.
    if row.get('learning_source_for_sha256')==row.get('source_sha256') and row.get('learning_source_sha256'):
        effective['source_sha256']=row['learning_source_sha256']
    raw=json.dumps({'trial':effective,'controls':controls,'learner':3},sort_keys=True,allow_nan=False)
    return 'v3-'+hashlib.sha256(raw.encode()).hexdigest()[:24]


def load(root):
    try:
        path=root/'configs/trading_execution.json'
        if path.stat().st_size>25000:return {}
        data=json.loads(path.read_text())
        return data if isinstance(data,dict) else {}
    except (OSError,ValueError):return {}


def validation_ok(report,scope):
    """Minimum review requirements, not a promise of statistical profitability."""
    if not isinstance(report,dict):return False
    b,f=report.get('backtest',{}),report.get('forward_paper',{})
    def at_least(row,key,minimum):return finite(row.get(key)) and row[key]>=minimum
    return (report.get('schema')==1 and report.get('scope')==scope
        and report.get('reviewed_by_user') is True and report.get('status')=='passed'
        and isinstance(b,dict) and isinstance(f,dict)
        and b.get('independent_out_of_sample') is True and b.get('costs_included') is True
        and b.get('lookahead_checked') is True and at_least(b,'coverage_days',90)
        and at_least(b,'out_of_sample_trades',100) and finite(b.get('net_r')) and b['net_r']>0
        and at_least(f,'days',14) and at_least(f,'trades',100) and f.get('gaps')==0
        and finite(f.get('lower_mean_r')) and f['lower_mean_r']>0
        and report.get('news_mode')=='report_only' and report.get('additional_positions') is False)


def authorize(root,snapshot,strategy=None,now=None):
    now=time.time() if now is None else now;policy=load(root)
    denied={'allowed':False,'status':'research_only','selected':None,
            'reason':'Order execution disabled pending independent validation and explicit review',
            'exploration_used':False,'news_mode':'report_only'}
    if (policy.get('schema')!=1 or policy.get('enabled') is not True
            or policy.get('reviewed_by_user') is not True):return denied
    if (type(snapshot.get('login')) is not int or snapshot['login']<=0
            or snapshot.get('symbol') not in ('XAUUSD','EURUSD','USDJPY')
            or type(snapshot.get('period')) is not int or snapshot['period']<=0):return denied
    scope={'account':snapshot.get('login'),'symbol':snapshot.get('symbol'),
           'period':snapshot.get('period'),'exit_policy_version':POLICY_VERSION}
    if policy.get('mode')=='unvalidated_demo':
        consent=policy.get('unvalidated_demo_consent',{})
        start,end=consent.get('accepted_utc'),consent.get('expires_utc')
        timed=consent.get('time_limit_enabled') is not False
        if (snapshot.get('demo') is not True or consent.get('accepted') is not True
                or not finite(start) or not finite(now) or not 0<start<=now):return denied
        if timed and (not finite(end) or not now<end<=start+86400):
            return {**denied,'reason':'DEMO trial time authorization expired or invalid'}
        trials=policy.get('demo_trials',[])
        if not isinstance(trials,list):return denied
        matches=[e for e in trials if isinstance(e,dict) and e.get('scope')==scope]
        if len(matches)!=1:return denied
        row=matches[0];selected=row.get('strategy')
        cap=row.get('entry_cap_fraction',.0005)
        cash=row.get('entry_cap_cash')
        limited=row.get('entry_risk_limit_enabled') is not False
        if limited and (not finite(cap) or not 0<cap<=.0005):return denied
        if limited and cash is not None and (not finite(cash) or not 0<cash<=50):return denied
        adaptive=row.get('selection_mode')=='adaptive_demo'
        allowed=row.get('strategies') if adaptive else [selected]
        if (not isinstance(allowed,list) or not allowed
                or any(type(k) is not str or k not in {x[0] for x in CATALOG} for k in allowed)
                or len(set(allowed))!=len(allowed)
                or strategy is not None and strategy not in allowed):return denied
        try:
            if row.get('source_sha256')!=fingerprint(root):return denied
            from ultimate_khorshid.tools.trading_controls import read as read_controls
            controls=read_controls(root)
        except (OSError,ValueError):return denied
        return {'allowed':True,'status':'unvalidated_demo','selected':None if adaptive else selected,
            'selection_mode':'adaptive_demo' if adaptive else 'fixed','allowed_strategies':allowed,
            'profit_exit_mode':row.get('profit_exit_mode','standard'),
            'entry_cap_cash':cash if limited else None,'entry_risk_limit_enabled':limited,
            'entries_paused':policy.get('entries_paused') is True,
            'experiment_id':row.get('experiment_id'),
            'learning_regime':learning_identity(row,controls),
            'max_positions':controls['max_positions'],
            'code_revision':row.get('source_sha256'),
            'reason':'User-authorized unvalidated DEMO trial; adaptive selection and bounded risk' if adaptive else 'User-authorized unvalidated DEMO trial; fixed strategy and bounded risk',
            'validation_status':'not_validated','exploration_used':False,'news_mode':'report_only',
            'entry_cap_fraction':cap if limited else None,'trend_alignment_required':row.get('require_trend_alignment') is not False,
            'time_limit_enabled':timed,'approval_expires_utc':end if timed else None}
    entries=policy.get('approvals',[])
    if not isinstance(entries,list):return denied
    matches=[e for e in entries if isinstance(e,dict) and e.get('scope')==scope]
    if len(matches)!=1:return {**denied,'reason':'Exactly one frozen, scoped strategy approval is required'}
    row=matches[0];selected=row.get('strategy');start,end=row.get('approved_utc'),row.get('expires_utc')
    if (snapshot.get('demo') is not True or selected not in {x[0] for x in CATALOG}
            or strategy is not None and strategy!=selected
            or not finite(now) or not finite(start) or not finite(end)
            or not 0<start<=now<end<=start+30*86400):return denied
    try:
        if row.get('source_sha256')!=fingerprint(root):return {**denied,'reason':'Execution code changed after review'}
        relative=row.get('validation_report')
        if not isinstance(relative,str):return denied
        directory=(root/'reports/trading-validation').resolve()
        path=(root/relative).resolve()
        if not path.is_relative_to(directory) or path.stat().st_size>256000:return denied
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=row.get('validation_sha256'):return denied
        if not validation_ok(json.loads(raw),{**scope,'strategy':selected}):return denied
    except (OSError,ValueError,TypeError):return denied
    return {'allowed':True,'status':'reviewed_strategy','selected':selected,'reason':'Frozen reviewed strategy only',
            'exploration_used':False,'news_mode':'report_only','approval_expires_utc':end}


def select(root,snapshot,signals,context=None,now=None,learner=None):
    result=authorize(root,snapshot,now=now);name=result['selected']
    if result['allowed'] and result.get('selection_mode')=='adaptive_demo':
        if learner is None:
            return {**result,'selected':None,'approved_strategy':None,'utc':time.time() if now is None else now,
                    'market_context':context,'candidates':{},'context_paused':[],'score_details':{},
                    'waiting_for_trend':False,'reason':'Adaptive demo requires persistent experience'}
        learner.set_regime(result.get('learning_regime'))
        ranking=learner.rank(signals,context=context,allowed=result['allowed_strategies'])
        if load(root).get('entries_paused') is True:
            return {**result,**ranking,'allowed':False,'status':'entries_paused',
                    'paused_candidate':ranking['selected'],'selected':None,
                    'reason':'User-approved temporary entry pause; learning and position exits remain active',
                    'exploration_used':False,'waiting_for_trend':False}
        return {**result,**ranking,'approved_strategy':None,'waiting_for_trend':False,
                'exploration_used':bool(ranking['selected']),
                'utc':time.time() if now is None else now}
    direction=signals.get(name,[0])[-1] if name else 0
    chosen=name if direction in (-1,1) else None
    waiting_for_trend=False
    if chosen and result.get('trend_alignment_required'):
        expected='up' if direction==1 else 'down'
        if (not context or context.get('trend')!=expected
                or context.get('signal_bar')!=(snapshot.get('bars') or [{}])[-1].get('time')):
            chosen=None;waiting_for_trend=True
    return {**result,'selected':chosen,'approved_strategy':name,'utc':time.time() if now is None else now,
            'market_context':context,'candidates':{name:direction} if name else {},'context_paused':[],
            'score_details':{},'waiting_for_trend':waiting_for_trend,
            'reason':'Current trend does not confirm the frozen strategy signal' if waiting_for_trend
                     else result['reason'] if chosen or not result['allowed'] else 'Configured strategy has no current signal'}


def constrain(plan,root,snapshot,now=None,advice=None):
    if plan.get('action')!='open':return plan
    if load(root).get('entries_paused') is True:
        return {'status':'entries_paused','reason':'User-approved temporary entry pause; exits remain active'}
    from ultimate_khorshid.tools.trading_controls import read, revision
    if snapshot.get('controls_revision')!=revision(read(root)):
        return {'status':'research_only','reason':'Native/Python controls mismatch; publish controls before entry'}
    permission=authorize(root,snapshot,plan.get('strategy'),now)
    if not permission['allowed']:return {'status':permission['status'],'reason':permission['reason']}
    if advice is not None and advice.get('news_mode')!='report_only':
        return {'status':'research_only','reason':'Allocation was not produced under the reviewed news policy'}
    if plan.get('exit_profile') not in (None,'quick') or plan.get('thesis_expires_utc',0)!=0:
        return {'status':'research_only','reason':'News-driven staged exits are not independently validated'}
    if len(snapshot.get('positions',[]))>=permission.get('max_positions',1):
        return {'status':'research_only','reason':'Additional positions require separate validation; exits remain active'}
    if permission.get('entry_cap_fraction') is not None:
        fraction=plan.get('risk_fraction')
        if not finite(fraction) or fraction<=0:
            return {'status':'research_only','reason':'Missing bounded trial risk allocation'}
        cap=permission['entry_cap_fraction']
        if permission.get('entry_cap_cash') is not None:
            equity=snapshot.get('equity')
            if not finite(equity) or equity<=0 or snapshot.get('currency')!='USD':
                return {'status':'research_only','reason':'Fresh USD equity required for cash risk cap'}
            cap=min(cap,permission['entry_cap_cash']/equity)
        return {**plan,'risk_fraction':min(fraction,cap),
            'experiment_id':permission.get('experiment_id'),
            'execution_mode':'unvalidated_demo','validation_status':'not_validated'}
    if permission.get('experiment_id'):
        return {**plan,'experiment_id':permission['experiment_id'],'execution_mode':'unvalidated_demo'}
    return plan


def require(root,snapshot,strategy=None):
    permission=authorize(root,snapshot,strategy)
    if not permission['allowed']:raise ValueError(permission['reason'])
    if load(root).get('entries_paused') is True:raise ValueError('User-approved temporary entry pause')
    if len(snapshot.get('positions',[]))>=permission.get('max_positions',1):raise ValueError('Additional positions are not approved')
    return permission
