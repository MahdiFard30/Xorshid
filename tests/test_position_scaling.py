import pytest
from ultimate_khorshid.tools.position_scaling import assess
from ultimate_khorshid.tools import portfolio_policy


def inputs():
    s={'max_positions':2,'bars':[{'time':100}],
       'positions':[{'direction':1,'progress_r':.3,'profit':20}]}
    c={'direction':1,'market_context':{'signal_bar':100,'trend':'up','efficiency':.5}}
    return s,c


def test_addition_needs_profitable_position_and_current_corroboration():
    s,c=inputs();assert assess(s,c,{}, {})['allow_entry']
    assert not assess(s,{'direction':1},{},{})['allow_entry']
    c['market_context']['signal_bar']=99
    assert not assess(s,c,{},{})['allow_entry']


@pytest.mark.parametrize('change',[{'profit':-1},{'progress_r':-.2},{'progress_r':.09},{'progress_r':None},{'direction':-1}])
def test_news_never_authorizes_averaging_down(change):
    s,c=inputs();s['positions'][0].update(change)
    c.update(headline_adjustment=.15,headline_has_article=True)
    assert not assess(s,c,{}, {'mode':'staged'})['allow_entry']


def test_native_limit_and_netting_capacity_are_never_overridden():
    s,c=inputs();s['positions']*=2
    assert not assess(s,c,{}, {'mode':'staged'})['allow_entry']
    s['positions']=s['positions'][:1];s['max_positions']=1
    assert not assess(s,c,{}, {'mode':'staged'})['allow_entry']


def test_first_entry_is_not_blocked_by_missing_extra_confirmation():
    s,c=inputs();s['positions']=[]
    assert assess(s,{'direction':1},{},{})['allow_entry']
    assert not assess(s,{'direction':0},{},{})['allow_entry']


def test_independent_indicator_families_and_opposing_signals():
    s,c=inputs();c={'direction':1,'signal_bar':100,'signals':{'ema_cross':1,'macd':1}}
    assert not assess(s,c,{},{})['allow_entry']
    c['signals']['stochastic']=1
    assert assess(s,c,{},{})['allow_entry']
    c['signals']['roc']=-1
    assert not assess(s,c,{},{})['allow_entry']


def test_model_confidence_alone_does_not_authorize_addition():
    s,c=inputs();c={'direction':1,'confidence':1,'headline_adjustment':.15}
    assert not assess(s,c,{},{})['allow_entry']
    c['headline_has_article']=True
    assert assess(s,c,{},{})['allow_entry']
    c['headline_adjustment']=0
    assert not assess(s,c,{},{})['allow_entry']


def test_positive_history_requires_sufficient_verified_evidence():
    s,c=inputs();c={'direction':1}
    assert not assess(s,c,{'verified_samples':19,'lower_mean_r_heuristic':.2},{})['allow_entry']
    assert not assess(s,c,{'verified_samples':20,'lower_mean_r_heuristic':-.2},{})['allow_entry']
    assert assess(s,c,{'verified_samples':20,'lower_mean_r_heuristic':.2},{})['allow_entry']


def test_extra_positions_use_existing_risk_headroom_and_never_raise_caps():
    from test_portfolio_policy import inputs as portfolio_inputs, NOW
    a,c,o,n=portfolio_inputs()
    a['EURUSD']['positions']=[{'direction':1,'progress_r':.4,'profit':20,'sl_risk_cash':80}]
    c['EURUSD']['market_context']={'signal_bar':a['EURUSD']['bars'][-1]['time'],'trend':'up','efficiency':.5}
    result=portfolio_policy.allocate(a,c,o,n,NOW)
    row=result['symbols']['EURUSD']
    assert row['position_scaling']['allow_entry'] and row['entry_budget_fraction']>0
    assert row['entry_budget_fraction']+80/100000<=row['symbol_budget_fraction']+1e-9
    assert sum(v['execution_entry_budget_fraction'] for v in result['symbols'].values())+.0008<=.005
    c['EURUSD']['market_context']={}
    assert portfolio_policy.allocate(a,c,o,n,NOW)['symbols']['EURUSD']['entry_budget_fraction']==0
