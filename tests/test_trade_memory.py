"""Use synthetic execution and temporary journals; never access broker files."""
import json
from pathlib import Path

import pytest

from ultimate_khorshid.tools.trade_memory import TradeMemory
from ultimate_khorshid.tools.demo_learning import Experience, NAMES
from ultimate_khorshid.tools import mt5_multi_worker as worker

STRATEGY = NAMES[0]


def snapshot(login=123, positions=None, deals=None, period=5):
    return {'login': login, 'symbol': 'EURUSD', 'period': period, 'currency': 'USD', 'balance': 100000.,
            'equity': 100000., 'bid': 1.1, 'ask': 1.1001, 'tick_age_seconds': 1,
            'bars': [{'time': 100, 'open': 1.1, 'close': 1.101}], 'period_seconds': 300,
            'positions': positions or [], 'deals': deals or []}


def entry(ticket=1, position=10, order=20, login=123, volume=.1, risk=10.):
    return {'ticket': ticket, 'position_id': position, 'order': order, 'entry': 0, 'time': 100,
            'volume': volume, 'price': 1.1, 'profit': 0., 'commission': -.5, 'swap': 0., 'fee': -.1,
            'net': -.6, 'comment': 'KH:'+STRATEGY, 'reason': 3,
            'initial_risk': {'method': 'entry_fill_sl_estimate', 'login': login, 'symbol': 'EURUSD',
                'deal': ticket, 'order': order, 'position_id': position, 'entry_time': 100, 'cash': risk,
                'currency':'USD','volume':volume,'price':1.1,'sl':1.099,'capture_lag_seconds':0}}


def exit_deal(ticket=2, position=10, volume=.1, profit=15.):
    return {'ticket': ticket, 'position_id': position, 'order': ticket+100, 'entry': 1, 'time': 200,
            'volume': volume, 'price': 1.101, 'profit': profit, 'commission': -.5, 'swap': -.2, 'fee': -.1,
            'net': profit-.8, 'comment': 'broker exit text', 'reason': 5}


def link(memory, s, request=1000, order=20):
    run = {'id':'run-a','news_filter':{'allow_entry':True},'entry_decision':{'plan':{'reason':'signal','exit_policy_version':2}}}
    memory.record_intent(run,s,request,'open',1,.002,.003,STRATEGY,())
    memory.record_ack(s['login'],{'id':request,'status':'executed','order':order})


def outcome(tmp_path, deals=None, positions=None, **snapshot_args):
    memory=TradeMemory(tmp_path/'journal.sqlite')
    s=snapshot(deals=deals or [entry(),exit_deal()],positions=positions,**snapshot_args)
    link(memory,s); memory.observe(s)
    return memory,s,memory.outcomes(s)['10']


def test_outcome_uses_entry_risk_and_all_deal_costs(tmp_path):
    memory,s,o=outcome(tmp_path)
    assert o['learning_eligible'] and o['closed_complete']
    assert o['net']==pytest.approx(13.6)
    assert o['normalized_reward']==pytest.approx(1.36)
    assert o['strategy']==STRATEGY  # Exit comment must not replace entry strategy.
    assert o['commission']==-1 and o['fee']==-.2
    assert o['entry_contexts'][0]['news']=={'allow_entry':True}
    assert o['exit_reasons']==[5]
    assert TradeMemory(memory.path).outcomes(s)==memory.outcomes(s)


@pytest.mark.parametrize('change,problem',[
    ({'initial_risk':None},'initial_risk_unavailable'),
    ({'volume':None},'volume_history_unavailable'),
    ({'volume':.2},'entry_exit_volume_mismatch'),
    ({'commission':None},'cost_breakdown_unavailable'),
    ({'entry':2},'missing_entry_exit_or_unsupported_reversal'),
])
def test_incomplete_evidence_never_scores(tmp_path,change,problem):
    _,_,o=outcome(tmp_path,deals=[dict(entry(),**change),exit_deal()])
    assert not o['learning_eligible']
    assert problem in o['evidence_problems']


def test_partial_exit_is_not_a_completed_trade(tmp_path):
    _,_,o=outcome(tmp_path,deals=[entry(),exit_deal(volume=.04)],positions=[{'identifier':10}])
    assert not o['closed_complete'] and not o['learning_eligible']


def test_full_volume_still_open_is_not_closed(tmp_path):
    _,_,o=outcome(tmp_path,positions=[{'identifier':10}])
    assert not o['learning_eligible']


def test_multiple_fills_and_partial_exits_score_only_when_balanced(tmp_path):
    memory,s,o=outcome(tmp_path,deals=[entry(volume=.04,risk=4),entry(ticket=3,volume=.06,risk=6),
                                      exit_deal(volume=.05,profit=5),exit_deal(ticket=4,volume=.05,profit=8)])
    assert o['learning_eligible'] and o['risk_cash']==10
    assert len(o['deal_tickets'])==4
    memory.observe(s)  # Repeated snapshots cannot double count deals.
    assert memory.outcomes(s)['10']['net']==o['net']


@pytest.mark.parametrize('field,value',[('login',999),('deal',999),('position_id',999),('cash',0),
                                       ('method','historical_recalculation'),('entry_time',99),('order',999),
                                       ('currency','JPY'),('volume',.2),('price',2.),('capture_lag_seconds',61)])
def test_foreign_or_invalid_entry_risk_not_used(tmp_path,field,value):
    d=entry(); d['initial_risk'][field]=value
    _,_,o=outcome(tmp_path,deals=[d,exit_deal()])
    assert not o['learning_eligible']


def test_missing_or_wrong_timeframe_order_link_is_not_inferred(tmp_path):
    memory=TradeMemory(tmp_path/'journal.sqlite'); s=snapshot(deals=[entry(),exit_deal()])
    link(memory,snapshot(period=15)); memory.observe(s)
    assert not memory.outcomes(s)['10']['learning_eligible']
    assert not memory.outcomes(s)['10']['entry_contexts']


def test_lost_ack_remains_unattributed_until_exact_ack_arrives(tmp_path):
    memory=TradeMemory(tmp_path/'journal.sqlite'); s=snapshot(deals=[entry(),exit_deal()])
    memory.observe(s)
    assert not memory.outcomes(s)['10']['learning_eligible']
    memory.record_ack(s['login'],{'id':999,'status':'executed','order':20})
    assert not memory.outcomes(s)['10']['learning_eligible']
    link(memory,s)
    assert memory.outcomes(s)['10']['learning_eligible']


def test_accounts_with_same_ticket_numbers_are_isolated(tmp_path):
    memory=TradeMemory(tmp_path/'journal.sqlite')
    for login in (123,456):
        s=snapshot(login=login,deals=[entry(login=login),exit_deal(profit=login)])
        link(memory,s); memory.observe(s)
    a=memory.outcomes(snapshot(login=123))['10']
    b=memory.outcomes(snapshot(login=456))['10']
    assert a['net']!=b['net']
    assert a['learning_eligible'] and b['learning_eligible']


def test_deals_survive_a_run_boundary_and_shorter_history_window(tmp_path):
    memory=TradeMemory(tmp_path/'journal.sqlite'); s=snapshot(deals=[entry()])
    link(memory,s); memory.observe(s)
    newer=snapshot(deals=[exit_deal()])
    memory=TradeMemory(memory.path); memory.observe(newer)
    assert memory.outcomes(newer)['10']['learning_eligible']


def test_verified_learning_is_once_only_across_restart(tmp_path):
    _,s,o=outcome(tmp_path)
    learner=Experience(tmp_path/'experience.json'); learner.activate(s)
    learner.learn_live({'10':o},999999,set())
    assert learner.summary()['demo_closed_learned']==1
    assert learner.data['stats'][STRATEGY]['verified_demo_mean_r']==pytest.approx(1.36)
    learner=Experience(learner.path)
    learner.learn_live({'10':o},.01,set())
    assert learner.summary()['demo_closed_learned']==1


def test_legacy_approximate_results_preserved_but_not_verified(tmp_path):
    learner=Experience(tmp_path/'experience.json')
    learner.data['stats'][STRATEGY].update(demo_n=10,demo_mean_r=2.,demo_net=100.)
    learner.save(); learner=Experience(learner.path)
    assert learner.summary()['legacy_demo_closed_approximate']==10
    assert learner.summary()['demo_closed_learned']==0
    assert learner.score(STRATEGY,explore=False)==0


def test_open_or_incomplete_result_does_not_change_learning(tmp_path):
    _,s,o=outcome(tmp_path,positions=[{'identifier':10}])
    learner=Experience(tmp_path/'experience.json'); learner.activate(s)
    learner.learn_live({'10':o},25,set())
    assert learner.summary()['demo_closed_learned']==0


def test_request_journal_committed_before_publish_failure(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'execution_guard',lambda *a,**k:None)
    monkeypatch.setattr(worker,'execution_gate',lambda value,*a,**k:value)
    folder=tmp_path/'channel'; folder.mkdir()
    monkeypatch.setattr(worker,'storage',lambda:tmp_path)
    monkeypatch.setattr(worker,'files',lambda:folder)
    def fail(*args): raise OSError('publish failed')
    monkeypatch.setattr(worker,'atomic',fail)
    from ultimate_khorshid.tools.managed_exits import entry_profile
    s={**snapshot(),'executor_version':9,'exit_policy_version':2}
    plan=entry_profile({'action':'open','direction':1,'risk_fraction':.001,'symbol_cap_fraction':.005},s,{},0)
    with pytest.raises(OSError): worker.send({'id':'run-a','entry_decision':{'plan':plan}},s,'open',1,.001,STRATEGY)
    memory=TradeMemory(tmp_path/'trade_memory.sqlite')
    with memory.connect() as con:
        assert con.execute('SELECT count(*) FROM intents').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM acknowledgements').fetchone()[0]==0
    assert not (folder/'khorshid_demo_request.tsv').exists()


def test_blocked_decisions_are_retained_without_inventing_execution(tmp_path):
    memory=TradeMemory(tmp_path/'journal.sqlite'); s=snapshot()
    run={'id':'run-a','entry_decision':{'plan':{'status':'news_window','reason':'High impact news'}}}
    memory.record_decision(run,s); memory.record_decision(run,s)
    assert memory.summary(s)['decisions_recorded']==1
    assert memory.summary(s)['positions_observed']==0
    with memory.connect() as con:
        assert con.execute('SELECT count(*) FROM intents').fetchone()[0]==0


def test_temporary_missing_risk_cannot_erase_captured_evidence(tmp_path):
    memory,s,o=outcome(tmp_path)
    memory.observe(dict(s,deals=[dict(entry(),initial_risk=None),exit_deal()]))
    assert memory.outcomes(s)['10']['learning_eligible']
    assert memory.outcomes(s)['10']['risk_cash']==10


def test_legacy_result_cannot_be_credited_again_as_new_evidence(tmp_path):
    _,s,o=outcome(tmp_path)
    learner=Experience(tmp_path/'experience.json'); learner.activate(s)
    learner.data['live_seen'].append('10')
    learner.learn_live({'10':o},None,set())
    assert learner.summary()['demo_closed_learned']==0
