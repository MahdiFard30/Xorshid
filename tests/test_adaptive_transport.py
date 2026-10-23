import pytest

from ultimate_khorshid.tools import mt5_multi_worker as worker
from ultimate_khorshid.tools.trade_memory import TradeMemory


def snapshot():
    return {'executor_version':9,'exit_policy_version':2,'login':7,'symbol':'EURUSD','period':15,'currency':'USD',
        'balance':100000.,'equity':100000.,'bid':1.1,'ask':1.1001,'tick_age_seconds':0,
        'bars':[{'time':100}],'executor_instance':'boot'}


def test_protocol9_transports_reduced_risk_and_journals_it_before_request(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'execution_guard',lambda *a,**k:None)
    monkeypatch.setattr(worker,'execution_gate',lambda value,*a,**k:value)
    monkeypatch.setattr(worker,'storage',lambda:tmp_path)
    monkeypatch.setattr(worker,'files',lambda:tmp_path)
    run={'id':'run','entry_decision':{'plan':{'action':'open','strategy':'macd','risk_fraction':.0001,'symbol_cap_fraction':.0004,'exit_policy_version':2,'stop_atr':1.,'target_r':1.,'exit_profile':'quick','thesis_expires_utc':0}}}
    worker.send(run,snapshot(),'open',1,.002,'macd')
    fields=(tmp_path/'khorshid_demo_request.tsv').read_text().strip().split('\t')
    assert len(fields)==16
    assert float(fields[12])==.0001 and float(fields[13])==.0004
    with TradeMemory(tmp_path/'trade_memory.sqlite').connect() as con:
        assert con.execute('SELECT count(*) FROM intents').fetchone()[0]==1


@pytest.mark.parametrize('fraction',[None,0,.005001,float('nan')])
def test_missing_or_oversized_risk_is_rejected_before_journal_or_publish(tmp_path,monkeypatch,fraction):
    monkeypatch.setattr(worker,'execution_guard',lambda *a,**k:None)
    monkeypatch.setattr(worker,'execution_gate',lambda value,*a,**k:value)
    monkeypatch.setattr(worker,'storage',lambda:tmp_path)
    monkeypatch.setattr(worker,'files',lambda:tmp_path)
    run={'id':'run','entry_decision':{'plan':{'action':'open','strategy':'macd','risk_fraction':fraction,'symbol_cap_fraction':.005,'exit_policy_version':2,'stop_atr':1.,'target_r':1.,'exit_profile':'quick','thesis_expires_utc':0}}}
    with pytest.raises(ValueError):worker.send(run,snapshot(),'open',1,.002,'macd')
    assert not (tmp_path/'khorshid_demo_request.tsv').exists()
    assert not (tmp_path/'trade_memory.sqlite').exists()


def test_exit_transport_does_not_require_portfolio_advice(tmp_path,monkeypatch):
    monkeypatch.setattr(worker,'storage',lambda:tmp_path)
    monkeypatch.setattr(worker,'files',lambda:tmp_path)
    worker.send({'id':'run'},snapshot(),'close_tickets',tickets=(123,))
    fields=(tmp_path/'khorshid_demo_request.tsv').read_text().strip().split('\t')
    assert fields[4]=='close_tickets' and fields[11]=='123'
