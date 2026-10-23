import hashlib
import fcntl
import json

import pytest

from ultimate_khorshid.tools import research_observer as observer
from ultimate_khorshid.tools.trade_memory import TradeMemory


def setup(tmp_path):
    root=tmp_path/'project'; terminal=tmp_path/'terminal'; symbol='EURUSD'
    directory=root/'.khorshid-multi'/symbol;directory.mkdir(parents=True)
    (directory/'state.json').write_text(json.dumps({'login':7,'period':15}))
    TradeMemory(directory/'trade_memory.sqlite')
    bars=[{'time':i*900,'open':100.,'high':101.,'low':99.,'close':100.,'spread':2} for i in range(1000)]
    snapshot={'demo':True,'connected':True,'generated_utc':100.,'login':7,'period':15,
              'symbol':symbol,'currency':'USD','period_seconds':900,'positions':[],
              'bars':bars,'point':.01,'bid':100.,'ask':100.02}
    files=terminal/'MQL5/Files/khorshid_multi'/symbol;files.mkdir(parents=True)
    path=files/'khorshid_demo_snapshot.json';path.write_text(json.dumps(snapshot))
    return root,terminal,symbol,path


def digest(directory):
    return {str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in directory.rglob('*') if p.is_file()}


def test_observer_cannot_change_broker_files_or_execution_journal(tmp_path,monkeypatch):
    root,terminal,symbol,path=setup(tmp_path)
    before=digest(terminal)
    journal=root/'.khorshid-multi'/symbol/'trade_memory.sqlite'
    journal_before=journal.read_bytes()
    def analyze(self,snapshot):
        return {'experiment_id':'fake','status':'no_candidate','candidate_before_holdout':None,
                'hypotheses_tested':30,'overlaps_previous_holdout':False,'automatic_deployment':False}
    monkeypatch.setattr(observer.StrategyLab,'analyze',analyze)
    result=observer.observe_symbol(root,terminal,symbol,now=100)
    assert not result['broker_writes'] and not result['execution_uses_context']
    assert result['latest_experiment']['hypotheses_tested']==30
    assert digest(terminal)==before
    assert journal.read_bytes()==journal_before


@pytest.mark.parametrize('change', [{'demo':False},{'connected':False},{'generated_utc':1},{'login':99}])
def test_live_stale_or_mismatched_data_do_not_start_research(tmp_path,change):
    root,terminal,symbol,path=setup(tmp_path)
    data=json.loads(path.read_text());data.update(change);path.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        observer.observe_symbol(root,terminal,symbol,now=100)
    assert not (root/'.khorshid-research').exists()


def test_existing_observer_lock_prevents_duplicate_launch(tmp_path,monkeypatch):
    output=tmp_path/'.khorshid-research';output.mkdir()
    def forbidden(*args,**kwargs):
        raise AssertionError('Duplicate observer launched')
    monkeypatch.setattr(observer.subprocess,'Popen',forbidden)
    with (output/'observer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert observer.ensure_started(tmp_path)=={'status':'already_running'}


def test_observer_launch_is_detached_and_contains_no_trading_action(tmp_path,monkeypatch):
    from types import SimpleNamespace
    calls=[]
    def launch(command,**kwargs):
        calls.append((command,kwargs))
        return SimpleNamespace(pid=123)
    monkeypatch.setattr(observer.subprocess,'Popen',launch)
    assert observer.ensure_started(tmp_path)['pid']==123
    command,kwargs=calls[0]
    assert command==[observer.sys.executable,str(tmp_path/'scripts/research_trader.py')]
    assert kwargs['start_new_session'] and kwargs['close_fds']
