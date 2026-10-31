import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from ultimate_khorshid.tools.demo_learning import Experience
from ultimate_khorshid.tools.research_observer import reconcile_stopped
from ultimate_khorshid.tools.trade_memory import TradeMemory


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    if not shutil.which('g++'):pytest.skip('C++ compiler required')
    folder=tmp_path_factory.mktemp('risk-data')
    header=Path(__file__).resolve().parents[1]/'mt5/RestartPolicy.mqh'
    source=folder/'test.cpp'
    source.write_text('#include <iostream>\n#include <cstdlib>\n#include "'+str(header)+'"\n'
        'int main(int n,char** v){ if(v[1][0]==\'q\') std::cout<<RiskQuoteData('
        'atof(v[2]),atof(v[3]),atol(v[4]),atol(v[5]),atol(v[6]),n>7?atol(v[7]):5);'
        'else std::cout<<RiskEquityData(atof(v[2]),atof(v[3]),atof(v[4]),atof(v[5]),atof(v[6]));}')
    binary=folder/'test'
    subprocess.run(['g++',str(source),'-o',str(binary)],check=True,capture_output=True)
    return lambda mode,*v:subprocess.check_output([str(binary),mode,*map(str,v)],text=True)=='1'


@pytest.mark.parametrize('bid,ask,stamp,msc,now',[
    (0,157.8,1000,1000000,1000),(157.8,157.7,1000,1000000,1000),
    (157.8,157.9,0,0,1000),(157.8,157.9,10,10000,1000),
    (157.8,157.9,1000,2000000,1000),(157.8,157.9,1001,1001000,1000),
    (float('nan'),157.9,1000,1000000,1000),
])
def test_native_rejects_invalid_prices_and_timestamps(native,bid,ask,stamp,msc,now):
    assert not native('q',bid,ask,stamp,msc,now)


def test_native_accepts_fresh_quotes_and_coherent_real_losses(native):
    assert native('q',157.8,157.9,1000,1000999,1005)
    assert native('e',100000,0,97000,-3000,0)
    assert native('e',100000,0,-1000,-101000,0)
    assert native('e',100000,0,100038.05,38.05,0)
    assert not native('e',100000,0,-431570593.06,-5.29,0)
    assert not native('e',100000,0,0,0,0)


def test_entry_retains_existing_120_second_quote_window(native):
    assert not native('q',157.8,157.9,1000,1000000,1100)
    assert native('q',157.8,157.9,1000,1000000,1100,120)
    assert not native('q',157.8,157.9,1000,1000000,1121,120)


def stopped_fixture(tmp_path):
    from test_trade_memory import snapshot,entry,exit_deal,link,STRATEGY
    root=tmp_path/'root';directory=root/'.khorshid-multi/EURUSD';directory.mkdir(parents=True)
    memory=TradeMemory(directory/'trade_memory.sqlite');s=snapshot(deals=[entry()])
    s.update(demo=True)
    link(memory,s);memory.observe(s)
    key=hashlib.sha256(b'123:EURUSD:5').hexdigest()[:20]
    learner=Experience(directory/'experience'/(key+'.json'));learner.data['account']=123;learner.save()
    s['deals'].append(exit_deal())
    state={'id':'run-a','login':123,'period':5,'status':'stop_pending','ended_utc':1}
    return root,directory,memory,s,state,learner.path,STRATEGY


def test_late_exit_is_imported_and_learned_exactly_once_without_orders(tmp_path):
    root,directory,memory,s,state,path,strategy=stopped_fixture(tmp_path)
    assert not memory.outcomes(s)['10']['closed_complete']
    result=reconcile_stopped(root,'EURUSD',s,state)
    assert result['learned_results']==1 and result['orders_sent'] is False
    assert memory.outcomes(s)['10']['closed_complete']
    assert Experience(path).data['stats'][strategy]['verified_demo_n']==1
    assert reconcile_stopped(root,'EURUSD',s,state)['learned_results']==0
    assert Experience(path).data['stats'][strategy]['verified_demo_n']==1


def test_active_worker_lock_prevents_observer_writes(tmp_path):
    root,directory,memory,s,state,path,strategy=stopped_fixture(tmp_path)
    before=path.read_bytes()
    with (directory/'runner.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        assert reconcile_stopped(root,'EURUSD',s,state) is None
    assert path.read_bytes()==before
    assert not memory.outcomes(s)['10']['closed_complete']


@pytest.mark.parametrize('change',[{'login':999},{'period':15},{'demo':False},{'symbol':'USDJPY'}])
def test_reconciliation_never_crosses_account_or_chart_scope(tmp_path,change):
    root,directory,memory,s,state,path,strategy=stopped_fixture(tmp_path)
    s.update(change)
    with pytest.raises(ValueError):reconcile_stopped(root,'EURUSD',s,state)
