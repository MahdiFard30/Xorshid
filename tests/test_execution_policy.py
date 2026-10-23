import hashlib
import json
import pytest
from ultimate_khorshid.tools import execution_policy as policy
from ultimate_khorshid.tools import mt5_multi_worker as worker

NOW=100000.


def snapshot():
    return {'login':7,'symbol':'EURUSD','period':5,'demo':True,'positions':[]}


def approved(tmp_path,monkeypatch):
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    scope={'account':7,'symbol':'EURUSD','period':5,'exit_policy_version':2,'strategy':'macd'}
    report={'schema':1,'status':'passed','reviewed_by_user':True,'scope':scope,
        'news_mode':'report_only','additional_positions':False,
        'backtest':{'independent_out_of_sample':True,'costs_included':True,'lookahead_checked':True,
                    'coverage_days':120,'out_of_sample_trades':120,'net_r':10},
        'forward_paper':{'days':20,'trades':120,'gaps':0,'lower_mean_r':.1}}
    path=tmp_path/'reports/trading-validation/review.json';path.parent.mkdir(parents=True);path.write_text(json.dumps(report))
    approval={'scope':{k:v for k,v in scope.items() if k!='strategy'},'strategy':'macd','approved_utc':NOW-10,
        'expires_utc':NOW+3600,'source_sha256':'reviewed-code','validation_report':str(path.relative_to(tmp_path)),
        'validation_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    data={'schema':1,'enabled':True,'reviewed_by_user':True,'approvals':[approval]}
    config=tmp_path/'configs/trading_execution.json';config.parent.mkdir();config.write_text(json.dumps(data))
    return config,path,data


def test_missing_disabled_or_malformed_policy_denies_execution(tmp_path):
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']
    config=tmp_path/'configs/trading_execution.json';config.parent.mkdir()
    for raw in ('{', '[]', '{"schema":1,"enabled":true}', '{"schema":1,"enabled":false}'):
        config.write_text(raw)
        assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']


def test_selection_is_frozen_and_ignores_other_strategies_and_learning(tmp_path,monkeypatch):
    approved(tmp_path,monkeypatch)
    result=policy.select(tmp_path,snapshot(),{'macd':[1],'stochastic':[-1]},now=NOW)
    assert result['selected']=='macd' and result['exploration_used'] is False
    result=policy.select(tmp_path,snapshot(),{'macd':[0],'stochastic':[1]},now=NOW)
    assert result['selected'] is None and result['allowed']


@pytest.mark.parametrize('change',[{'login':8},{'symbol':'XAUUSD'},{'period':15},{'demo':False}])
def test_approval_cannot_cross_account_symbol_timeframe_or_demo_scope(tmp_path,monkeypatch,change):
    approved(tmp_path,monkeypatch)
    assert not policy.authorize(tmp_path,{**snapshot(),**change},now=NOW)['allowed']


def test_code_or_validation_changes_invalidate_approval(tmp_path,monkeypatch):
    config,path,data=approved(tmp_path,monkeypatch)
    monkeypatch.setattr(policy,'fingerprint',lambda root:'changed')
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path.write_text(path.read_text()+' ')
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']


def test_expired_future_duplicate_and_wrong_strategy_approvals_are_rejected(tmp_path,monkeypatch):
    config,path,data=approved(tmp_path,monkeypatch)
    assert not policy.authorize(tmp_path,snapshot(),'roc',NOW)['allowed']
    assert not policy.authorize(tmp_path,snapshot(),now=NOW+3601)['allowed']
    assert not policy.authorize(tmp_path,snapshot(),now=NOW-20)['allowed']
    data['approvals']*=2;config.write_text(json.dumps(data))
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']


def test_unreviewed_insufficient_or_reused_evidence_cannot_authorize(tmp_path,monkeypatch):
    config,path,data=approved(tmp_path,monkeypatch)
    report=json.loads(path.read_text());scope=report['scope']
    assert policy.validation_ok(report,scope)
    for field,value in [('out_of_sample_trades',5),('independent_out_of_sample',False),('lookahead_checked',False),('net_r',-1)]:
        changed={**report,'backtest':{**report['backtest'],field:value}}
        assert not policy.validation_ok(changed,scope)
    for field,value in [('trades',8),('days',1),('lower_mean_r',-.1),('gaps',1)]:
        assert not policy.validation_ok({**report,'forward_paper':{**report['forward_paper'],field:value}},scope)


def test_unapproved_open_is_blocked_before_journal_but_exit_remains_available(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    monkeypatch.setattr(worker,'storage',lambda:tmp_path)
    monkeypatch.setattr(worker,'files',lambda:tmp_path)
    with pytest.raises(ValueError):worker.send({'id':'run'},snapshot(),'open',1,1,'macd')
    assert not (tmp_path/'trade_memory.sqlite').exists()
    assert not (tmp_path/'khorshid_demo_request.tsv').exists()
    s={**snapshot(),'currency':'USD','bars':[{'time':100}],'balance':100,'equity':100,'bid':1,'ask':1.01,'tick_age_seconds':0}
    worker.send({'id':'run'},s,'close_tickets',tickets=(123,))
    assert (tmp_path/'khorshid_demo_request.tsv').read_text().split('\t')[4]=='close_tickets'


def test_start_block_does_not_clear_user_stop_or_launch_process(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'ROOT',tmp_path);monkeypatch.setattr(worker,'storage',lambda:tmp_path)
    monkeypatch.setattr(worker,'files',lambda:tmp_path);monkeypatch.setattr(worker,'running',lambda:False)
    monkeypatch.setattr(worker,'snapshot',snapshot)
    flag=tmp_path/'khorshid_demo_stop.flag';flag.write_text('user stop')
    monkeypatch.setattr(worker.subprocess,'Popen',lambda *a,**k:pytest.fail('Unexpected worker launch'))
    with pytest.raises(ValueError):worker.start()
    assert flag.read_text()=='user stop'


def test_denied_execution_never_blocks_exit_plans(tmp_path):
    close={'action':'close_tickets','tickets':[1]}
    assert policy.constrain(close,tmp_path,snapshot(),NOW) is close
    assert policy.constrain({'action':'open','strategy':'macd'},tmp_path,snapshot(),NOW)['status']=='research_only'


def test_positive_research_screen_does_not_create_execution_permission(tmp_path):
    folder=tmp_path/'.khorshid-multi/EURUSD';folder.mkdir(parents=True)
    (folder/'qualified_strategies.json').write_text(json.dumps({'selected':'macd','candidates':{'macd':{'return_pct':100}}}))
    result=policy.select(tmp_path,snapshot(),{'macd':[1]},now=NOW)
    assert result['selected'] is None and not result['allowed']


def test_reviewed_report_cannot_be_loaded_from_outside_validation_directory(tmp_path,monkeypatch):
    config,path,data=approved(tmp_path,monkeypatch)
    data['approvals'][0]['validation_report']='../../external.json'
    config.write_text(json.dumps(data))
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']


def test_reviewed_technical_strategy_rejects_old_news_allocation_and_staged_exits(tmp_path,monkeypatch):
    approved(tmp_path,monkeypatch)
    plan={'action':'open','strategy':'macd','exit_profile':'quick','thesis_expires_utc':0}
    assert policy.constrain(plan,tmp_path,snapshot(),NOW,advice={'news_mode':'report_only'}) is plan
    assert policy.constrain(plan,tmp_path,snapshot(),NOW,advice={})['status']=='research_only'
    assert policy.constrain({**plan,'exit_profile':'staged'},tmp_path,snapshot(),NOW)['status']=='research_only'
    assert policy.constrain(plan,tmp_path,{**snapshot(),'positions':[{'identifier':1}]},NOW)['status']=='research_only'


def trial(root):
    scope={'account':7,'symbol':'EURUSD','period':5,'exit_policy_version':2}
    return {'schema':1,'enabled':True,'reviewed_by_user':True,'mode':'unvalidated_demo',
            'unvalidated_demo_consent':{'accepted':True,'accepted_utc':NOW-10,'expires_utc':NOW+3600},
            'demo_trials':[{'scope':scope,'strategy':'macd','source_sha256':'reviewed-code'}]}


def test_explicit_unvalidated_trial_is_demo_only_temporary_scoped_and_truthfully_labeled(tmp_path,monkeypatch):
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path=tmp_path/'configs/trading_execution.json';path.parent.mkdir();data=trial(tmp_path)
    path.write_text(json.dumps(data))
    permission=policy.authorize(tmp_path,snapshot(),now=NOW)
    assert permission['allowed'] and permission['validation_status']=='not_validated'
    assert permission['entry_cap_fraction']==.0005 and not permission['exploration_used']
    assert not policy.authorize(tmp_path,{**snapshot(),'demo':False},now=NOW)['allowed']
    assert not policy.authorize(tmp_path,{**snapshot(),'login':8},now=NOW)['allowed']
    assert not policy.authorize(tmp_path,snapshot(),now=NOW+3601)['allowed']
    data['unvalidated_demo_consent']['accepted']=False;path.write_text(json.dumps(data))
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']


def test_unvalidated_trial_requires_current_trend_confirmation_and_caps_risk(tmp_path,monkeypatch):
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path=tmp_path/'configs/trading_execution.json';path.parent.mkdir();path.write_text(json.dumps(trial(tmp_path)))
    s={**snapshot(),'bars':[{'time':100}]}
    assert policy.select(tmp_path,s,{'macd':[1]},context={'trend':'down','signal_bar':100},now=NOW)['selected'] is None
    assert policy.select(tmp_path,s,{'macd':[1]},context={'trend':'up','signal_bar':100},now=NOW)['selected']=='macd'
    plan={'action':'open','strategy':'macd','risk_fraction':.002,'exit_profile':'quick','thesis_expires_utc':0}
    result=policy.constrain(plan,tmp_path,s,NOW,advice={'news_mode':'report_only'})
    assert result['risk_fraction']==.0005
    assert policy.constrain(result,tmp_path,s,NOW,advice={'news_mode':'report_only'})==result


def test_demo_trial_can_explicitly_disable_extra_trend_filter_without_forcing_signals(tmp_path,monkeypatch):
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path=tmp_path/'configs/trading_execution.json';path.parent.mkdir();data=trial(tmp_path)
    data['demo_trials'][0]['require_trend_alignment']=False
    path.write_text(json.dumps(data))
    s={**snapshot(),'bars':[{'time':100}]}
    result=policy.select(tmp_path,s,{'macd':[1]},context={'trend':'down','signal_bar':100},now=NOW)
    assert result['selected']=='macd' and not result['waiting_for_trend']
    assert result['entry_cap_fraction']==.0005 and result['news_mode']=='report_only'
    assert policy.select(tmp_path,s,{'macd':[0]},now=NOW)['selected'] is None
    assert not policy.authorize(tmp_path,{**s,'demo':False},now=NOW)['allowed']


def test_adaptive_demo_learns_persists_and_never_requires_macd(tmp_path,monkeypatch):
    from ultimate_khorshid.tools.demo_learning import Experience
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path=tmp_path/'configs/trading_execution.json';path.parent.mkdir();data=trial(tmp_path)
    data['demo_trials'][0].update(selection_mode='adaptive_demo',strategies=['sma_cross','rsi_rebound'])
    path.write_text(json.dumps(data))
    learner=Experience(tmp_path/'experience.json')
    signals={'sma_cross':[1],'rsi_rebound':[-1],'macd':[1]}
    def select(l):return policy.select(tmp_path,snapshot(),signals,now=NOW,learner=l)
    assert select(learner)['selected']=='sma_cross'
    learner.reward('sma_cross','verified_demo',-1,-50)
    learner.reward('rsi_rebound','verified_demo',1,50)
    learner.save();reloaded=Experience(learner.path)
    result=select(reloaded)
    assert result['selected']=='rsi_rebound' and result['exploration_used']
    assert set(result['score_details'])=={'sma_cross','rsi_rebound'}
    assert not reloaded.data['decisions']  # Observer previews must not write the worker's state.
    assert policy.authorize(tmp_path,snapshot(),'rsi_rebound',NOW)['allowed']
    assert not policy.authorize(tmp_path,snapshot(),'macd',NOW)['allowed']
    assert not policy.authorize(tmp_path,{**snapshot(),'demo':False},'rsi_rebound',NOW)['allowed']
    assert policy.select(tmp_path,snapshot(),signals,now=NOW)['selected'] is None
    assert policy.select(tmp_path,snapshot(),{'macd':[1]},now=NOW,learner=reloaded)['selected'] is None
    plan={'action':'open','strategy':'rsi_rebound','risk_fraction':.01}
    assert policy.constrain(plan,tmp_path,snapshot(),NOW,{'news_mode':'report_only'})['risk_fraction']==.0005


@pytest.mark.parametrize('strategies',[[],['missing'],['sma_cross','sma_cross'],[{}],None])
def test_adaptive_demo_rejects_invalid_catalog(tmp_path,monkeypatch,strategies):
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path=tmp_path/'configs/trading_execution.json';path.parent.mkdir();data=trial(tmp_path)
    data['demo_trials'][0].update(selection_mode='adaptive_demo',strategies=strategies)
    path.write_text(json.dumps(data))
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']


def test_lower_risk_demo_caps_fraction_and_cash_and_labels_the_experiment(tmp_path,monkeypatch):
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path=tmp_path/'configs/trading_execution.json';path.parent.mkdir();data=trial(tmp_path)
    data['demo_trials'][0].update(entry_cap_fraction=.0001,entry_cap_cash=10.,
        profit_exit_mode='standard',experiment_id='balanced-1r-10usd')
    path.write_text(json.dumps(data))
    plan={'action':'open','strategy':'macd','risk_fraction':.002,'exit_profile':'quick','thesis_expires_utc':0}
    def apply(equity):return policy.constrain(plan,tmp_path,{**snapshot(),'equity':equity,'currency':'USD'},NOW,{'news_mode':'report_only'})
    assert apply(200000)['risk_fraction']==.00005
    assert apply(50000)['risk_fraction']==.0001
    assert apply(200000)['experiment_id']=='balanced-1r-10usd'
    assert policy.constrain(plan,tmp_path,snapshot(),NOW)['status']=='research_only'
    assert apply(float('nan'))['status']=='research_only'
    assert policy.authorize(tmp_path,snapshot(),now=NOW)['profit_exit_mode']=='standard'
    for bad in (0,-1,.001,float('nan')):
        data['demo_trials'][0]['entry_cap_fraction']=bad;path.write_text(json.dumps(data))
        assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']


def test_user_can_remove_demo_execution_expiry_without_extending_it_to_a_hidden_deadline(tmp_path,monkeypatch):
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path=tmp_path/'configs/trading_execution.json';path.parent.mkdir();data=trial(tmp_path)
    data['unvalidated_demo_consent'].update(time_limit_enabled=False,expires_utc=None)
    path.write_text(json.dumps(data))
    for later in (NOW,NOW+86400*30,NOW+86400*365*5):
        p=policy.authorize(tmp_path,snapshot(),now=later)
        assert p['allowed'] and p['time_limit_enabled'] is False and p['approval_expires_utc'] is None
        assert p['entry_cap_fraction']==.0005 and p['news_mode']=='report_only'
        assert not policy.authorize(tmp_path,{**snapshot(),'demo':False},now=later)['allowed']
        assert not policy.authorize(tmp_path,{**snapshot(),'login':8},now=later)['allowed']
    data['unvalidated_demo_consent']['accepted']=False;path.write_text(json.dumps(data))
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']


def test_missing_expiry_does_not_silently_remove_the_existing_timed_policy(tmp_path,monkeypatch):
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    path=tmp_path/'configs/trading_execution.json';path.parent.mkdir();data=trial(tmp_path)
    data['unvalidated_demo_consent'].pop('expires_utc');path.write_text(json.dumps(data))
    assert not policy.authorize(tmp_path,snapshot(),now=NOW)['allowed']
