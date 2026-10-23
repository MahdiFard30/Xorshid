import json
from pathlib import Path
import shutil
import sqlite3
import subprocess

import pytest

from ultimate_khorshid.tools import trading_controls as controls
from ultimate_khorshid.tools import execution_policy as policy
from ultimate_khorshid.tools.entry_protections import assess
from ultimate_khorshid.tools.demo_learning import Experience,NAMES
from ultimate_khorshid.tools.history_archive import Archive
from ultimate_khorshid.tools.trade_memory import TradeMemory
from scripts.trading_review import backup,restore,verify


def test_approved_controls_disable_both_pauses_even_without_a_clock(tmp_path):
    p=tmp_path/'configs/trading_controls.json';p.parent.mkdir()
    p.write_text(json.dumps({'schema':1,'settings':{'cooldown_bars':0,'stop_cluster_enabled':False,'news_entry_block_enabled':False}}))
    values=controls.read(tmp_path)
    assert assess({'trading_controls':values},{},True)['allow_entry']
    assert assess({'trading_controls':values},{})['allow_entry']
    assert values['daily_loss_fraction']==.02 and values['max_hold_bars']==24
    tag=controls.publish(tmp_path,tmp_path/'terminal')
    raw=(tmp_path/'terminal/MQL5/Files/khorshid_multi/shared-controls.tsv').read_text()
    assert 'cooldown_bars\t0\n' in raw and 'stop_cluster_enabled\t0\n' in raw and tag==controls.revision(values)


def test_explicit_removal_of_entry_caps_does_not_substitute_a_fifty_dollar_cap(tmp_path,monkeypatch):
    from test_execution_policy import trial,snapshot,NOW
    monkeypatch.setattr(policy,'fingerprint',lambda root:'reviewed-code')
    data=trial(tmp_path);data['demo_trials'][0].update(entry_risk_limit_enabled=False,entry_cap_fraction=None,entry_cap_cash=None)
    p=tmp_path/'configs/trading_execution.json';p.parent.mkdir();p.write_text(json.dumps(data))
    permission=policy.authorize(tmp_path,snapshot(),now=NOW)
    assert permission['allowed'] and permission['entry_cap_cash'] is None and permission['entry_cap_fraction'] is None
    plan={'action':'open','strategy':'macd','risk_fraction':.002,'exit_profile':'quick','thesis_expires_utc':0}
    assert policy.constrain(plan,tmp_path,snapshot(),NOW,{'news_mode':'report_only'})['risk_fraction']==.002
    assert not policy.authorize(tmp_path,{**snapshot(),'demo':False},now=NOW)['allowed']


def test_all_decision_retries_ack_revisions_and_deal_corrections_are_preserved(tmp_path):
    from test_trade_memory import snapshot,entry
    memory=TradeMemory(tmp_path/'journal.sqlite');s=snapshot(deals=[entry()])
    run={'id':'r','entry_decision':{'utc':1,'plan':{'reason':'waiting'}},'experiment_id':'e','learning_regime':'standard'}
    memory.record_decision(run,s)
    run['entry_decision']={'utc':2,'plan':{'reason':'ready'}};memory.record_decision(run,s)
    memory.record_decision(run,s)  # Identical observation does not add a fake revision.
    memory.record_intent(run,s,5,'open',1,.01,.01,NAMES[0],())
    memory.record_ack(123,{'id':5,'status':'not_confirmed'})
    memory.record_ack(123,{'id':5,'status':'executed','order':20})
    memory.record_ack(123,{'id':999,'status':'rejected','note':'orphan evidence'})
    memory.observe(s);memory.observe(s)
    s['deals'][0]['commission']=-2;memory.observe(s)
    with sqlite3.connect(memory.archive.path) as con:
        counts=dict(con.execute('SELECT kind,count(*) FROM revisions GROUP BY kind'))
        assert counts['decision']==2 and counts['ack']==3 and counts['deal']==2
        assert con.execute('SELECT payload FROM revisions WHERE kind="deal" ORDER BY id LIMIT 1').fetchone()
    assert memory.summary(s)['decisions_recorded']==1  # Legacy summary remains compatible.


def test_observed_profit_path_and_regime_labels_survive_closure(tmp_path):
    from test_trade_memory import snapshot,entry,exit_deal
    memory=TradeMemory(tmp_path/'journal.sqlite')
    s=snapshot(deals=[entry()],positions=[{'identifier':10,'profit':5.,'swap':-.1,'progress_r':.5}])
    s['generated_utc']=1000
    run={'id':'r','entry_decision':{'plan':{'exit_policy_version':2}},'experiment_id':'e','learning_regime':'standard'}
    memory.record_intent(run,s,5,'open',1,.01,.01,NAMES[0],())
    memory.record_ack(123,{'id':5,'status':'executed','order':20})
    memory.observe(s)
    s['generated_utc']=1001;s['positions'][0].update(profit=-3.,progress_r=-.3);memory.observe(s)
    s['positions']=[];s['deals'].append(exit_deal());memory.observe(s)
    o=memory.outcomes(s)['10']
    assert o['experiment_id']=='e' and o['learning_regime']=='standard'
    assert o['observed_path']['max_floating_profit']==5 and o['observed_path']['min_floating_profit']==-3
    assert o['observed_path']['samples']==2


def test_learning_regimes_do_not_mix_scores_or_delete_prior_experience(tmp_path):
    learner=Experience(tmp_path/'experience.json')
    learner.reward(NAMES[0],'verified_demo',1,10)
    learner.set_regime('first-positive');learner.reward(NAMES[0],'verified_demo',-1,-10)
    old_context=learner.context_path()
    learner.set_regime('standard');assert learner.score(NAMES[0],False)==0
    assert learner.context_path()!=old_context
    learner.reward(NAMES[1],'verified_demo',1,10);learner.save()
    reloaded=Experience(learner.path);assert reloaded.score(NAMES[0],False)==1
    reloaded.set_regime('first-positive');assert reloaded.score(NAMES[0],False)==-1
    reloaded.set_regime('standard');assert reloaded.score(NAMES[1],False)==1


def test_only_same_regime_closed_outcomes_update_live_scores(tmp_path):
    from test_trade_memory import outcome
    _,_,closed=outcome(tmp_path/'journal')
    learner=Experience(tmp_path/'experience.json');learner.data['account']=123
    learner.set_regime('standard')
    closed['learning_regime']='first-positive'
    learner.learn_live({'10':closed},None,set())
    assert learner.stats[NAMES[0]]['verified_demo_n']==0
    closed['learning_regime']='standard'
    learner.learn_live({'10':closed},None,set());learner.learn_live({'10':closed},None,set())
    assert learner.stats[NAMES[0]]['verified_demo_n']==1


def test_archive_revisions_backup_restore_and_corruption_detection(tmp_path):
    root=tmp_path/'project';db=root/'.khorshid-multi/EURUSD/trade_memory.history.sqlite'
    archive=Archive(db)
    archive.save('decision','x',{'reason':'A'});archive.save('decision','x',{'reason':'B'})
    archive.save('decision','x',{'reason':'A'})
    archive.save('invalid_input','x',{'value':float('nan')})
    result=backup(root,tmp_path/'backup');assert result['verified']
    assert restore(tmp_path/'backup',tmp_path/'restore')['verified']
    with sqlite3.connect(tmp_path/'restore/.khorshid-multi/EURUSD/trade_memory.history.sqlite') as con:
        assert con.execute('SELECT count(*) FROM revisions').fetchone()[0]==4
    restored=tmp_path/'restore/.khorshid-multi/EURUSD/trade_memory.history.sqlite'
    restored.write_bytes(b'corrupted')
    with pytest.raises(ValueError):verify(tmp_path/'restore')


def test_native_disabled_pauses_match_python_for_recent_stops(tmp_path):
    compiler=shutil.which('g++')
    if not compiler:pytest.skip('C++ compiler unavailable')
    header=Path(__file__).resolve().parents[1]/'mt5/RestartPolicy.mqh'
    source=tmp_path/'controls.cpp'
    source.write_text('#include <cmath>\n#include <algorithm>\nusing namespace std;\n#include "'+str(header)+'"\n'
        'int main(){return EntryPauseUntil(1000,300,999,8,999,10,999,0,false)==0?0:1;}\n')
    subprocess.run([compiler,'-std=c++17',str(source),'-o',str(tmp_path/'controls')],check=True,capture_output=True)
    subprocess.run([str(tmp_path/'controls')],check=True)
