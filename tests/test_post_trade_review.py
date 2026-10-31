import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from ultimate_khorshid.tools.post_trade_review import ReviewStore,review,collect


def evidence():
    outcome={'account':7,'symbol':'EURUSD','position_id':'10','strategy':'donchian',
        'closed_complete':True,'learning_eligible':True,'net':-10.,'risk_cash':10.,
        'normalized_reward':-1.,'commission':0.,'fee':0.,'swap':0.,'exit_reasons':[4],
        'deal_tickets':[1,2],'entry_contexts':[{'recorded_utc':99.,'request_id':8,
            'direction':1,'bid':1.1,'ask':1.1001,'sl_distance_requested':.001,
            'decision':{'plan':{'reason':'recorded signal'},'market_context':{'trend':'down'},
                'learning':{'score_details':{'donchian':{'evidence_before_exploration':-.1,
                    'context_adjustment':-.02,'demo_results':8,'risk_multiplier':1.}}}}}]}
    deals=[{'entry':0,'price':1.1005,'initial_risk':{'captured_utc':100}}]
    return outcome,deals


def labels(result):return {f['label'] for f in result['possible_factors']}


def test_loss_produces_evidence_not_an_invented_cause_or_new_entry_rule():
    outcome,deals=evidence();before=copy.deepcopy(outcome)
    result=review(outcome,deals,5)
    assert result['result']=='loss' and result['exact_cause']=='undetermined'
    assert 'negative_entry_evidence' in labels(result)
    assert 'adverse_fill_vs_recorded_request' in labels(result)
    assert all(not f['causal_proof'] for f in result['possible_factors'])
    assert result['report_only'] and not result['affects_scoring']
    assert result['entry_evidence']['recorded_reason']=='recorded signal'
    assert 'alternative_exit_not_tested' in result['evidence_gaps']
    assert outcome==before


def test_win_is_not_automatically_a_correct_decision():
    o,d=evidence();o['net']=10.;o['normalized_reward']=1.
    result=review(o,d,5)
    assert result['result']=='win' and 'negative_entry_evidence' in labels(result)
    assert result['exact_cause']=='undetermined'


def test_open_or_partial_positions_cannot_be_counted_as_completed_successes():
    o,d=evidence();o['closed_complete']=False;o['net']=10.
    result=review(o,d,5)
    assert result['result']=='open_or_incomplete' and not result['possible_factors']


def test_missing_or_late_entry_evidence_never_becomes_a_pre_entry_explanation():
    o,d=evidence();o['entry_contexts'][0]['recorded_utc']=200
    result=review(o,d,5)
    assert 'entry_evidence_timing_unverified' in result['evidence_gaps']
    assert 'negative_entry_evidence' not in labels(result)
    o['entry_contexts']=[];result=review(o,d,None)
    assert result['entry_evidence']['recorded_reason'] is None
    assert result['scope']['period'] is None


def test_large_corrupt_excursions_are_retained_and_flagged_without_exit_claims():
    o,d=evidence();o['observed_path']={'min_progress_r':-20000000.,'samples':1}
    result=review(o,d,5)
    assert 'implausible_excursion_samples_unverified' in result['evidence_gaps']
    assert result['facts']['observed_excursions']['min_progress_r']==-20000000.
    assert not any('exit' in label for label in labels(result))


def test_cost_drag_is_separate_from_spread_and_direction_error():
    o,d=evidence();o.update(commission=-2.,fee=-.5)
    result=review(o,d,5)
    cost=next(f for f in result['possible_factors'] if f['label']=='explicit_cost_drag')
    assert cost['evidence']['cost_drag_r']==.25
    assert 'direction_error' not in labels(result)


def test_repeated_reads_restart_and_restored_backup_do_not_duplicate_or_delete_reviews(tmp_path):
    o,d=evidence();report=review(o,d,5);path=tmp_path/'reviews.sqlite'
    store=ReviewStore(path);assert store.append(report)
    assert not ReviewStore(path).append(report)
    changed=copy.deepcopy(report);changed['facts']['net']=-11.
    assert store.append(changed)
    other=copy.deepcopy(report);other['scope']['account']=8
    assert store.append(other)
    restored=tmp_path/'restored.sqlite'
    with sqlite3.connect(path) as src,sqlite3.connect(restored) as dst:src.backup(dst)
    assert not ReviewStore(restored).append(report)
    with sqlite3.connect(restored) as con:
        assert con.execute('pragma integrity_check').fetchone()[0]=='ok'
        assert con.execute('select count(*) from reviews').fetchone()[0]==3


def test_source_journals_configs_and_terminal_files_remain_unchanged(tmp_path):
    from test_trade_memory import outcome
    root=tmp_path/'project';terminal=tmp_path/'terminal';sources=[]
    for symbol in ('XAUUSD','EURUSD','USDJPY'):
        folder=root/'.khorshid-multi'/symbol;folder.mkdir(parents=True)
        memory,s,_=outcome(folder)
        s.update(symbol=symbol,demo=True,generated_utc=time.time())
        (folder/'state.json').write_text(json.dumps({'login':s['login'],'period':s['period']}))
        # The fixture creates journal.sqlite; this is an isolated test DB.
        memory.path.rename(folder/'trade_memory.sqlite')
        channel=terminal/'MQL5/Files/khorshid_multi'/symbol;channel.mkdir(parents=True)
        p=channel/'khorshid_demo_snapshot.json';p.write_text(json.dumps(s));sources+=[p,folder/'state.json',folder/'trade_memory.sqlite']
    before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    store=ReviewStore(tmp_path/'separate/reviews.sqlite');result=collect(root,terminal,store)
    assert result['orders_sent'] is False and not result['errors']
    assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    path=terminal/'MQL5/Files/khorshid_multi/EURUSD/khorshid_demo_snapshot.json'
    stale=json.loads(path.read_text());stale['generated_utc']-=1000;path.write_text(json.dumps(stale))
    result=collect(root,terminal,store)
    assert all(r['result']=='open_or_incomplete' for r in result['reviews'])
    assert all('stale_terminal_snapshot' in r['evidence_gaps'] for r in result['reviews'])


def test_invalid_prospective_samples_are_labelled_and_retained(tmp_path):
    store=ReviewStore(tmp_path/'reviews.sqlite')
    s={'login':7,'symbol':'EURUSD','period':5,'generated_utc':time.time(),
       'account_data_valid':False,'bid':0.,'ask':0.,'positions':[{'identifier':10}]}
    store.capture(s);store.capture(s)
    with sqlite3.connect(store.path) as con:
        rows=con.execute('select data from observations').fetchall()
    assert len(rows)==1 and json.loads(rows[0][0])['account_data_valid'] is False


def test_source_failures_remain_explicit_and_durable_without_orders(tmp_path):
    store=ReviewStore(tmp_path/'reviews.sqlite')
    result=collect(tmp_path/'missing-root',tmp_path/'missing-terminal',store)
    assert set(result['errors'])=={'XAUUSD','EURUSD','USDJPY'}
    assert result['reviewed_positions']==0 and result['orders_sent'] is False
    summary={k:v for k,v in result.items() if k!='reviews'}
    store.record_run(summary)
    with sqlite3.connect(store.path) as con:
        saved=json.loads(con.execute('select data from runs').fetchone()[0])
    assert saved['errors']==result['errors']
