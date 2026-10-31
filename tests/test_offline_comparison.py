import importlib.util
from pathlib import Path

import pytest


@pytest.fixture
def comparison():
    path=Path(__file__).resolve().parents[1]/'scripts/compare_adaptive.py'
    spec=importlib.util.spec_from_file_location('offline_comparison',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def snapshot():
    return {'symbol':'EURUSD','point':.00001,'period_seconds':300,
            'bars':[{'time':1700000100+i*300,'open':1.1,'high':1.11,'low':1.09,
                     'close':1.1,'spread':2} for i in range(1000)]}


@pytest.mark.parametrize('change',[
    {'low':0},{'high':1.0},{'open':float('nan')},{'spread':-1},
    {'time':1700000100},{'time':1700000101},
])
def test_invalid_candles_are_not_used_for_performance_claims(comparison,change):
    data=snapshot();data['bars'][500].update(change)
    with pytest.raises(ValueError):comparison.compare(data,{})


@pytest.mark.parametrize('mode',['frozen','walk_forward'])
def test_holdout_rewards_never_reach_current_decision_and_freeze_is_real(comparison,monkeypatch,mode):
    observed=[];rewards=[]
    class Learner:
        def __init__(self,path):pass
        def set_regime(self,regime):pass
        def rank(self,signals,allowed):
            observed.append(len(rewards))
            return {'selected':None,'risk_multiplier':0,'selection_stage':'no_entry'}
        def reward(self,*args):rewards.append(args)
    monkeypatch.setattr(comparison,'Experience',Learner)
    names=[n for n,_,_ in comparison.CATALOG if n!='macd']
    monkeypatch.setattr(comparison,'indicators',lambda bars:({n:[1]*1000 for n in names},[.01]*1000))
    monkeypatch.setattr(comparison,'step',lambda *args,**kw:[{'kind':'close','r':1}])
    monkeypatch.setattr(comparison,'simulate',lambda *args,**kw:{})
    result=comparison.compare(snapshot(),{},mode=mode)
    boundary=600-61
    assert observed[boundary]==boundary*len(names)
    assert observed[boundary+1]==observed[boundary]+(len(names) if mode=='walk_forward' else 0)
    assert observed[-1]==observed[boundary]+((999-600)*len(names) if mode=='walk_forward' else 0)
    assert result['evaluation_mode']==mode
    assert result['automatic_deployment'] is False


def test_gaps_are_disclosed_without_fabricating_candles(comparison):
    data=snapshot()
    for b in data['bars'][500:]:b['time']+=300
    assert comparison.validate(data)['gap_count']==1
