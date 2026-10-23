import json
import sqlite3

import pytest

from ultimate_khorshid.tools.market_learning import ContextModel, describe
from ultimate_khorshid.tools.demo_learning import Experience, NAMES
from ultimate_khorshid.tools.trade_memory import TradeMemory


def bars(n=100, trend=1, start=100000):
    return [{'time':start+i*900,'open':100+i*.1*trend,'close':100+i*.1*trend+.02,
             'high':100+i*.1*trend+.3,'low':100+i*.1*trend-.3,'spread':2} for i in range(n)]


def outcome(ident='1', reward=-1., context=None, account=7):
    context=context or describe(bars(),utc=100000,spread=.02)
    return {'account':account,'position_id':ident,'strategy':NAMES[0],
        'normalized_reward':reward,'net':reward*20,'learning_eligible':True,'closed_complete':True,
        'risk_cash':20.,'normalization':'verified entry risk','deal_tickets':[1,2],
        'entry_contexts':[{'action':'open','direction':1,'strategy':NAMES[0],
                           'decision':{'market_context':context,'plan':{'exit_policy_version':2}}}]}


def test_causal_context_is_identical_when_future_changes():
    data=bars(120)
    expected=describe(data[:80],utc=100000,spread=.02)
    data[100]['close']=999999
    assert describe(data[:80],utc=100000,spread=.02)==expected
    assert expected['trend']=='up' and expected['volatility']=='normal'
    assert describe(bars(trend=-1))['trend']=='down'
    assert describe(bars(trend=0))['trend']=='range'


@pytest.mark.parametrize('bad', [[], bars(5), [dict(b,close=float('nan')) for b in bars()],list(reversed(bars()))])
def test_bad_context_is_not_invented(bad):
    assert describe(bad) is None


def test_context_results_are_verified_once_persisted_and_account_scoped(tmp_path):
    path=tmp_path/'model.sqlite'; model=ContextModel(path,7)
    group=outcome()
    assert model.observe({'1':group})==1
    assert ContextModel(path,7).observe({'1':group})==0
    assert ContextModel.summary(path,7)['verified_context_results']==1
    assert ContextModel.summary(path,8)['verified_context_results']==0


@pytest.mark.parametrize('change', [
    {'learning_eligible':False},{'closed_complete':False},{'normalized_reward':float('nan')},
    {'account':8},{'entry_contexts':[]},
])
def test_unverified_or_unlinked_results_do_not_learn(tmp_path,change):
    model=ContextModel(tmp_path/'model.sqlite',7)
    assert model.observe({'1':dict(outcome(),**change)})==0


def test_open_positions_never_score(tmp_path):
    model=ContextModel(tmp_path/'model.sqlite',7)
    assert model.observe({'1':outcome()},open_ids={1})==0


def test_entry_context_not_exit_market_drives_score_and_sparse_data_do_not_change_selection(tmp_path):
    model=ContextModel(tmp_path/'model.sqlite',7)
    up=describe(bars(),utc=100000,spread=.02); down=describe(bars(trend=-1),utc=100000,spread=.02)
    model.observe({str(i):outcome(str(i),context=up) for i in range(19)})
    assert model.assess(NAMES[0],up,1)['adjustment']==0
    model.observe({'19':outcome('19',context=up)})
    assert model.assess(NAMES[0],up,1)['adjustment']<0
    assert model.assess(NAMES[0],down,1)['samples']==0
    assert model.assess(NAMES[0],up,-1)['samples']==0


def test_persistent_negative_evidence_can_abstain_without_changing_exit_rules(tmp_path):
    learner=Experience(tmp_path/'experience.json'); learner.data['account']=7
    context=describe(bars(),utc=100000,spread=.02)
    learner.contextual().observe({str(i):outcome(str(i),context=context) for i in range(30)})
    signals={k:[int(k==NAMES[0])] for k in NAMES}
    assert learner.choose(signals,context=context) is None
    assert learner.data['decisions'][-1]['context_paused']==[NAMES[0]]
    assert learner.choose(signals)==NAMES[0]  # Compatibility when context is unavailable.


def test_context_evidence_changes_ranking_only_when_sufficient(tmp_path):
    learner=Experience(tmp_path/'experience.json');learner.data['account']=7
    context=describe(bars(),utc=100000,spread=.02)
    groups={}
    for i in range(20):
        groups[str(i)]=outcome(str(i),reward=-1,context=context)
        better=outcome(str(i+100),reward=1,context=context)
        better['strategy']=NAMES[1];better['entry_contexts'][0]['strategy']=NAMES[1]
        groups[str(i+100)]=better
    learner.contextual().observe(groups)
    signals={name:[int(name in NAMES[:2])] for name in NAMES}
    assert learner.choose(signals)==NAMES[0]
    assert learner.choose(signals,context=context)==NAMES[1]


def test_verified_history_can_be_enriched_without_recrediting_legacy_rewards(tmp_path):
    learner=Experience(tmp_path/'experience.json'); learner.data['account']=7
    learner.data['live_seen']=['1']
    learner.learn_live({'1':outcome()},None,set())
    assert learner.summary()['context_learning']['verified_context_results']==0
    learner.data['live_seen']=[]
    learner.learn_live({'1':outcome()},None,set())
    learner.learn_live({'1':outcome()},None,set())
    assert learner.summary()['context_learning']['verified_context_results']==1
    assert learner.summary()['demo_closed_learned']==1


def test_old_entry_journal_can_supply_only_its_actual_recorded_context(tmp_path):
    group=outcome()
    group['entry_contexts'][0].pop('decision')
    group['entry_contexts'][0].update(recent_closed_bars=bars(20),recorded_utc=100000,bid=110,ask=110.02)
    model=ContextModel(tmp_path/'model.sqlite',7)
    assert model.observe({'1':group})==1
    with model.connect() as con:
        context=json.loads(con.execute('SELECT context FROM outcomes').fetchone()[0])
    assert context['signal_bar']==bars(20)[-1]['time']
    assert context['volatility']=='unknown'  # Never pretend an absent longer history exists.


def test_execution_journal_opened_readonly_cannot_be_written(tmp_path):
    path=tmp_path/'journal.sqlite';TradeMemory(path)
    journal=TradeMemory.read_only(path)
    with journal.connect() as con:
        assert con.execute('SELECT count(*) FROM intents').fetchone()[0]==0
        with pytest.raises(sqlite3.OperationalError,match='readonly'):
            con.execute('DELETE FROM intents')


def test_context_storage_failure_preserves_verified_learning_and_final_score_filter(tmp_path,monkeypatch):
    learner=Experience(tmp_path/'experience.json');learner.data['account']=7
    model=learner.contextual()
    def fail(*args): raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr(model,'observe',fail)
    monkeypatch.setattr(model,'assess',fail)
    learner.learn_live({'1':outcome()},None,set())
    assert learner.summary()['demo_closed_learned']==1
    signals={name:[int(name==NAMES[0])] for name in NAMES}
    assert learner.choose(signals,context=describe(bars())) is None
    assert learner.data['decisions'][-1]['score_rejected']==[NAMES[0]]
    assert 'locked' in learner.data['decisions'][-1]['context_error']
    learner.reward(NAMES[0],'verified_demo',3,60)
    assert learner.choose(signals,context=describe(bars()))==NAMES[0]
    assert learner.summary()['demo_closed_learned']==2
