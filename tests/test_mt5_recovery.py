"""Restart scenarios use temporary files and fake demo data, never a terminal."""
import json
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from ultimate_khorshid.tools.mt5_recovery import Recovery, lease_text
from ultimate_khorshid.tools import mt5_multi_worker as worker


def sample(instance='boot-a', bar=100, positions=0):
    return {'executor_version':6,'executor_instance':instance,'schema':2,'demo':True,'generated_utc':1000,
            'period_seconds':3600,'broker_utc_offset_seconds':0,'connected':True,'login':123,'symbol':'EURUSD','period':16385,'currency':'USD',
            'balance':1000.,'equity':1000.,'point':.00001,'bid':1.1,'ask':1.1001,
            'tick_age_seconds':1,'bar_age_seconds':1,'entry_window_seconds':300,'max_positions':2,
            'algo_enabled':True,'halted':False,'own_positions':positions,'blocking_positions':0,
            'total_orders':0,'deals':[], 'positions':[{'identifier':1}] if positions else [],
            'bars':[{'time':bar}] * 1000}


def test_new_executor_detected_even_without_a_missing_snapshot():
    recovery = Recovery(sample())
    assert not recovery.observe(sample())
    assert recovery.observe(sample('boot-b'))
    assert not recovery.observe(sample('boot-b'))


def test_executor_cannot_silently_lose_restart_identity():
    legacy=sample()
    del legacy['executor_instance']
    recovery=Recovery(legacy)
    assert recovery.observe(sample('boot-new'))
    with pytest.raises(ValueError):
        recovery.observe(legacy)


def test_disconnect_blocks_entry_for_recovery_candle_but_allows_exits():
    recovery = Recovery(sample())
    assert recovery.unavailable(1000)
    assert not recovery.unavailable(1001)
    assert recovery.waiting_since == 1000
    assert recovery.observe(sample(bar=200,positions=1))
    assert recovery.waiting_since is None
    assert 'action' not in recovery.constrain({'action':'open'},200)
    close = {'action':'close_tickets','tickets':[1]}
    assert recovery.constrain(close,200) == close
    assert recovery.constrain({'action':'open'},201) == {'action':'open'}


def test_lease_acknowledges_exact_executor_instance_and_supports_legacy():
    s = sample()
    fields = lease_text(s,'a'*32,1000).strip().split('\t')
    assert fields == ['1000','123','a'*32,'EURUSD','16385','boot-a']
    del s['executor_instance']
    assert len(lease_text(s,'a'*32,1000).strip().split('\t')) == 5


@pytest.mark.parametrize('instance',['', 'bad\ninstance', 'bad\tinstance', 'x'*129, 123])
def test_invalid_instance_never_enters_lease(instance):
    with pytest.raises(ValueError):
        lease_text(sample(instance), 'a'*32,1000)


@pytest.fixture
def channels(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'ROOT',tmp_path)
    files=tmp_path/'terminal'; files.mkdir()
    storage=tmp_path/'worker'; storage.mkdir()
    monkeypatch.setattr(worker,'files',lambda:files)
    monkeypatch.setattr(worker,'storage',lambda:storage)
    monkeypatch.setattr(worker,'channel',lambda:'EURUSD')
    return files,storage


def publish(files,data):
    data = dict(data,generated_utc=worker.time.time())
    (files/'khorshid_demo_snapshot.json').write_text(json.dumps(data))


def test_snapshot_waits_for_history_and_partial_files_instead_of_stopping(channels):
    files,_=channels
    publish(files,dict(sample(),bars=[]))
    with pytest.raises(worker.SnapshotUnavailable): worker.snapshot()
    (files/'khorshid_demo_snapshot.json').write_text('{"executor_version":')
    with pytest.raises(worker.SnapshotUnavailable): worker.snapshot()
    (files/'khorshid_demo_snapshot.json').unlink()
    with pytest.raises(worker.SnapshotUnavailable): worker.snapshot()


def test_snapshots_accept_current_and_legacy_but_reject_live_accounts(channels):
    files,_=channels
    for version in (5,6,7,8,9):
        publish(files,dict(sample(),executor_version=version))
        assert worker.snapshot()['executor_version']==version
    publish(files,dict(sample(),demo=False))
    with pytest.raises(ValueError): worker.snapshot()
    publish(files,sample(''))
    with pytest.raises(ValueError): worker.snapshot()


def prepare_loop(monkeypatch,channels,sequence,plan):
    # Recovery tests isolate handover from sizing, with a valid reference budget.
    plan={**plan,'risk_fraction':.001,'symbol_cap_fraction':.005}
    files,storage=channels
    snapshots=iter(sequence)
    def snapshot():
        value=next(snapshots)
        if isinstance(value,Exception): raise value
        if value.get('_stop'):
            (files/'khorshid_demo_stop.flag').write_text('User requested portfolio stop')
        return value
    monkeypatch.setattr(worker,'snapshot',snapshot)
    monkeypatch.setattr(worker.signal,'signal',lambda *args:None)
    monkeypatch.setattr(worker.time,'sleep',lambda seconds:None)
    monkeypatch.setattr(worker,'report',lambda:None)
    monkeypatch.setattr('ultimate_khorshid.tools.research_observer.ensure_started',lambda root:None)
    monkeypatch.setattr(worker,'save_screen',lambda *args:None)
    monkeypatch.setattr(worker,'Calendar',lambda:SimpleNamespace(status=lambda symbol:{},close=lambda:None))
    monkeypatch.setattr(worker,'gate',lambda value,news:value)
    monkeypatch.setattr(worker,'portfolio_gate',lambda value,*args:value)
    monkeypatch.setattr(worker,'execution_gate',lambda value,*args,**kwargs:value)
    monkeypatch.setattr(worker,'execution_selection',lambda *a,**k:{'selected':'strategy','allowed':True,
        'context_paused':[],'reason':'Isolated recovery fixture; authorization tested separately'})
    monkeypatch.setattr(worker,'indicators',lambda bars:({},[1]))
    monkeypatch.setattr(worker,'decision',lambda *args:dict(plan))
    learner=SimpleNamespace(activate=lambda s:None,learn_live=lambda *a:None,advance=lambda *a:None,
                            choose=lambda s,context=None,news_adjustments=None:'strategy',attempted=lambda s:None,
                            event=lambda *a:None,save=lambda:None,data={'decisions':[{}]})
    monkeypatch.setattr('ultimate_khorshid.tools.demo_learning.Experience',lambda path:learner)
    sent=[]
    def send(run,s,action,*args,**kwargs):
        sent.append((action,s['bars'][-1]['time']))
        (files/'khorshid_demo_request.tsv').write_text('queued')
        run['last_request']=12345
    monkeypatch.setattr(worker,'send',send)
    return sent,files,storage


def test_allocation_delay_retries_inside_entry_window_without_duplicate_orders(monkeypatch,channels):
    first=sample()
    sequence=[first,first,first,first,dict(first,_stop=True)]
    sent,files,storage=prepare_loop(monkeypatch,channels,sequence,{'action':'open','direction':1,'strategy':'strategy','reason':'signal'})
    calls=[]
    def gate(plan,*args):
        calls.append(1)
        if len(calls)==1:return {'status':'waiting_for_portfolio_allocation','reason':'observer still reading new bar'}
        return plan
    clock=iter(range(0,100,3))
    monkeypatch.setattr(worker,'portfolio_gate',gate)
    monkeypatch.setattr(worker.time,'monotonic',lambda:next(clock))
    worker.run_loop()
    assert len(calls)==2
    assert sent==[('open',100)]


@pytest.mark.parametrize('status,note,retries',[
    ('rejected','Portfolio allocation busy; no order sent',2),
    ('not_confirmed','Timeout; execution unknown',1),
])
def test_only_explicit_pre_order_lock_rejection_can_be_retried(monkeypatch,channels,status,note,retries):
    first=sample();sequence=[first,first,first,first,dict(first,_stop=True)]
    sent,files,storage=prepare_loop(monkeypatch,channels,sequence,{'action':'open','direction':1,'strategy':'strategy','reason':'signal'})
    def send(run,s,action,*args):
        sent.append((action,s['bars'][-1]['time']))
        run['last_request']=len(sent)
        if len(sent)==1:
            (files/'khorshid_demo_ack.json').write_text(json.dumps({'id':1,'status':status,'note':note}))
    clock=iter(range(0,100,3))
    monkeypatch.setattr(worker,'send',send)
    monkeypatch.setattr(worker.time,'monotonic',lambda:next(clock))
    worker.run_loop()
    assert len(sent)==retries


@pytest.mark.parametrize('gap',[True,False])
def test_worker_recovers_without_replaying_entry_and_keeps_same_run(monkeypatch,channels,gap):
    first=sample()
    sequence=[first,first]
    if gap: sequence.append(worker.SnapshotUnavailable('restart'))
    sequence.extend([sample('boot-b',positions=1),sample('boot-b',bar=200,positions=1),
                     dict(sample('boot-b',bar=200),_stop=True)])
    sent,files,storage=prepare_loop(monkeypatch,channels,sequence,{'action':'open','direction':1,'reason':'signal'})
    worker.run_loop()
    assert sent==[('open',100),('open',200)]
    state=json.loads((storage/'state.json').read_text())
    assert state['status']=='stopped'
    assert state.get('reconnected_utc')
    assert 'User requested portfolio stop' in (files/'khorshid_demo_stop.flag').read_text()
    fields=(files/'khorshid_demo_lease.tsv').read_text().strip().split('\t')
    assert fields[2]==state['id'] and fields[-1]=='boot-b'


def test_manual_stop_during_disconnect_is_preserved(monkeypatch,channels):
    files,storage=channels
    first=sample()
    def stop_then_disconnect():
        (files/'khorshid_demo_stop.flag').write_text('User requested portfolio stop')
        raise worker.SnapshotUnavailable('terminal offline')
    values=iter([first,first])
    sent,_,_=prepare_loop(monkeypatch,channels,[first,first],{'status':'wait','reason':'no signal'})
    def snapshot():
        try: return next(values)
        except StopIteration: return stop_then_disconnect()
    monkeypatch.setattr(worker,'snapshot',snapshot)
    worker.run_loop()
    assert sent==[]
    state=json.loads((storage/'state.json').read_text())
    assert state['status']=='stop_pending'
    assert (files/'khorshid_demo_stop.flag').exists()


def test_changed_account_never_receives_new_lease(monkeypatch,channels):
    bad=dict(sample('boot-b'),login=999)
    sent,files,storage=prepare_loop(monkeypatch,channels,[sample(),bad,bad,bad],
                                   {'action':'open','reason':'signal'})
    worker.run_loop()
    assert sent==[]
    assert not (files/'khorshid_demo_lease.tsv').exists()
    assert json.loads((storage/'state.json').read_text())['status']=='stop_pending'


@pytest.fixture(scope='module')
def restart_policy_binary(tmp_path_factory):
    compiler=shutil.which('g++')
    if not compiler: pytest.skip('C++ compiler required for shared pure MQL/C++ policy test')
    folder=tmp_path_factory.mktemp('ea-restart-policy')
    header=Path(__file__).resolve().parents[1]/'mt5/RestartPolicy.mqh'
    source=folder/'policy.cpp'
    source.write_text('#include <iostream>\n#include <cstdlib>\n#include "'+str(header)+'"\n'
                      'int main(int n,char** v){std::cout << RestartPolicy(atoi(v[1]),atoi(v[2]),atoi(v[3]),atol(v[4]),atoi(v[5]));}\n')
    binary=folder/'policy'
    subprocess.run([compiler,str(source),'-o',str(binary)],check=True,capture_output=True)
    return binary


@pytest.mark.parametrize('stop,lease,reconciled,elapsed,protected,expected',[
    (1,1,0,0,1,2),   # Manual stop/risk stop always dominates a valid lease.
    (1,0,0,0,1,2),
    (0,1,0,0,1,1),   # Only a verified current-instance lease permits execution.
    (0,0,0,0,1,0),
    (0,0,0,14999,1,0),
    (0,0,0,15000,1,2),
    (0,0,0,0,0,2),   # No grace for missing SL/TP.
    (0,0,1,0,1,2),   # Normal lease loss after reconciliation keeps old protection.
    (0,0,0,-1,1,2),
])
def test_shared_ea_restart_policy(restart_policy_binary,stop,lease,reconciled,elapsed,protected,expected):
    result=subprocess.run([str(restart_policy_binary),*map(str,(stop,lease,reconciled,elapsed,protected))],
                          check=True,capture_output=True,text=True)
    assert int(result.stdout)==expected


def test_worker_waits_through_weekend_and_resumes_on_fresh_bar(monkeypatch,channels):
    paused=dict(sample(),weekly_schedule_known=True,weekly_close_paused=True)
    opened=dict(sample(),weekly_schedule_known=True,weekly_close_paused=False)
    next_bar=dict(opened,bars=[{'time':200}]*1000)
    sequence=[paused,paused,opened,next_bar,dict(next_bar,_stop=True)]
    sent,files,storage=prepare_loop(monkeypatch,channels,sequence,{'action':'open','direction':1,'reason':'signal'})
    worker.run_loop()
    assert sent==[('open',200)]
    assert json.loads((storage/'state.json').read_text())['status']=='stopped'
    assert 'User requested portfolio stop' in (files/'khorshid_demo_stop.flag').read_text()


def test_execution_disabled_cannot_be_overridden_by_an_exploratory_signal(monkeypatch,channels):
    from ultimate_khorshid.tools.execution_policy import select
    initial=sample();sequence=[initial,initial,dict(initial,_stop=True)]
    sent,files,storage=prepare_loop(monkeypatch,channels,sequence,{'action':'open','direction':1,'strategy':'strategy','reason':'exploratory candidate'})
    monkeypatch.setattr(worker,'execution_selection',select)
    worker.run_loop()
    assert sent==[]
    assert not (files/'khorshid_demo_request.tsv').exists()


def test_profit_exit_monitors_each_snapshot_without_waiting_for_a_new_candle(monkeypatch,channels):
    from ultimate_khorshid.tools import execution_policy
    s=sample(positions=1)
    s['positions']=[{'identifier':1,'ticket':22}]
    sequence=[s,s,s,s,dict(s,_stop=True,positions=[],own_positions=0)]
    sent,files,storage=prepare_loop(monkeypatch,channels,sequence,{'status':'waiting','reason':'no signal'})
    monkeypatch.setattr(execution_policy,'authorize',lambda *a,**k:{'profit_exit_mode':'first_positive_estimated_net'})
    calls=[]
    def exit_plan(snapshot):
        calls.append(1)
        return None if len(calls)==1 or not snapshot['positions'] else {'action':'close_tickets','tickets':[22],
            'reason':'positive estimated net','exit_details':[]}
    monkeypatch.setattr(worker,'first_positive_exit',exit_plan)
    worker.run_loop()
    assert sent==[('close_tickets',100)]


def test_supervised_resume_preserves_history_and_rejects_stale_or_wrong_lease(monkeypatch,channels):
    from ultimate_khorshid.tools import execution_policy
    files,storage=channels;s=sample()
    run={'id':'same-session','login':s['login'],'symbol':s['symbol'],'period':s['period'],
         'started_utc':12,'baseline_deals':[42]}
    (storage/'state.json').write_text(json.dumps(run))
    monkeypatch.setattr(execution_policy,'authorize',lambda *a,**k:{'allowed':True})
    monkeypatch.setattr(worker.time,'time',lambda:1000)
    (files/'khorshid_demo_lease.tsv').write_text(lease_text(s,run['id'],1000))
    result=worker.resumed_state(s)
    assert result['id']==run['id'] and result['started_utc']==12 and result['baseline_deals']==[42]
    (files/'khorshid_demo_lease.tsv').write_text(lease_text(s,'wrong-session',1000))
    with pytest.raises(ValueError):worker.resumed_state(s)
    (files/'khorshid_demo_lease.tsv').write_text(lease_text(s,run['id'],900))
    with pytest.raises(ValueError):worker.resumed_state(s)


def test_user_disabled_news_block_allows_entry_even_when_calendar_is_unavailable(monkeypatch,channels):
    from ultimate_khorshid.tools.mt5_news_calendar import gate
    s=sample();s['trading_controls']={'news_entry_block_enabled':False}
    sequence=[s,s,dict(s,_stop=True)]
    sent,files,storage=prepare_loop(monkeypatch,channels,sequence,{'action':'open','direction':1,'strategy':'strategy','reason':'signal'})
    monkeypatch.setattr(worker,'gate',gate)
    monkeypatch.setattr(worker,'Calendar',lambda:SimpleNamespace(status=lambda symbol:{'allow_entry':False,'status':'calendar_unavailable'},close=lambda:None))
    worker.run_loop()
    assert sent==[('open',100)]


@pytest.mark.parametrize('closing',[False,True])
def test_negative_score_wait_reason_is_saved_without_blocking_position_exit(monkeypatch,channels,closing):
    s=sample();sequence=[s,s,dict(s,_stop=True)]
    plan={'action':'close_tickets','tickets':[42],'reason':'existing position exit'} if closing else {
        'status':'waiting_for_entry_signal','reason':'no signal'}
    sent,files,storage=prepare_loop(monkeypatch,channels,sequence,plan)
    monkeypatch.setattr(worker,'execution_selection',lambda *a,**k:{'allowed':True,'selected':None,
        'score_rejected':['strategy'],'context_paused':[],'reason':'No non-negative final strategy score; entry declined'})
    worker.run_loop()
    decision=json.loads((storage/'state.json').read_text())['entry_decision']['plan']
    if closing:
        assert sent==[('close_tickets',100)] and decision['action']=='close_tickets'
    else:
        assert sent==[] and decision['status']=='waiting_for_nonnegative_strategy_score'
