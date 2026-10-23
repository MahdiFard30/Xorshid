import copy
import math
import random

import pytest

from ultimate_khorshid.tools import portfolio_policy as policy

NOW=1792497600


def inputs():
    bars=[{'time':1000+i*900,'close':100+math.sin(i*.3)+i*.03} for i in range(100)]
    snapshots={s:{'symbol':s,'login':7,'currency':'USD','period':15,'period_seconds':900,
        'demo':True,'connected':True,'generated_utc':NOW,'equity':100000.,'bars':copy.deepcopy(bars),
        'executor_version':9,'exit_policy_version':2,'broker_utc_offset_seconds':0,'adaptive_risk_schema':1,'risk_policy_version':2,'executor_instance':'boot-'+s,
        'algo_enabled':True,'halted':False,'stopped':False,'weekly_schedule_known':True,
        'weekly_close_paused':False,'blocking_positions':0,'total_orders':0,'positions':[],
        'max_positions':2,'bar_age_seconds':2,'entry_window_seconds':300,'tick_age_seconds':0} for s in policy.SYMBOLS}
    candidates={s:{'strategy':'macd','direction':1} for s in policy.SYMBOLS}
    return snapshots,candidates,{s:{} for s in policy.SYMBOLS},{s:1. for s in policy.SYMBOLS}


def outcome(symbol,ident,reward):
    return {'account':7,'symbol':symbol,'closed_complete':True,'learning_eligible':True,
            'normalized_reward':reward,'closed_time_server':ident,'entry_contexts':[{'decision':{'plan':{'exit_policy_version':2}}}]}


def test_balanced_sparse_evidence_and_caps_are_preserved():
    a,c,o,n=inputs();result=policy.allocate(a,c,o,n,NOW)
    assert result['execution_ready']
    for row in result['symbols'].values():
        assert row['weight']==pytest.approx(1/3)
        assert 0<row['entry_budget_fraction']<=policy.ENTRY_CAP
        assert row['entry_budget_fraction']<=row['symbol_budget_fraction']<=policy.SYMBOL_CAP
    assert sum(r['entry_budget_fraction'] for r in result['symbols'].values())<=policy.NEW_ENTRY_POOL


def test_one_recent_winner_cannot_take_over_allocation():
    a,c,o,n=inputs();o['XAUUSD']={'1':outcome('XAUUSD',1,1000)}
    result=policy.allocate(a,c,o,n,NOW)
    assert result['symbols']['XAUUSD']['weight']==pytest.approx(1/3)


def test_verified_evidence_can_change_weights_without_raising_caps():
    a,c,o,n=inputs()
    o['XAUUSD']={str(i):outcome('XAUUSD',i,1) for i in range(50)}
    o['EURUSD']={str(i):outcome('EURUSD',i,-1) for i in range(50)}
    rows=policy.allocate(a,c,o,n,NOW)['symbols']
    assert rows['XAUUSD']['weight']>rows['USDJPY']['weight']>rows['EURUSD']['weight']
    assert max(r['entry_budget_fraction'] for r in rows.values())<=policy.ENTRY_CAP


@pytest.mark.parametrize('change',[{'login':8},{'generated_utc':NOW-16},{'demo':False},{'equity':float('nan')},{'period_seconds':0}])
def test_mismatched_stale_and_invalid_snapshots_cannot_authorize_execution(change):
    a,c,o,n=inputs();a['EURUSD'].update(change)
    result=policy.allocate(a,c,o,n,NOW)
    assert not result['execution_ready'] and result['status']=='allocation_unavailable'


def test_legacy_executor_or_unknown_position_risk_is_not_silently_treated_as_zero():
    a,c,o,n=inputs();a['EURUSD']['executor_version']=6
    assert not policy.allocate(a,c,o,n,NOW)['execution_ready']
    a,c,o,n=inputs();a['EURUSD']['positions']=[{'direction':1}]
    result=policy.allocate(a,c,o,n,NOW)
    assert not result['execution_ready']
    assert all(r['entry_budget_fraction']==0 for r in result['symbols'].values())


def test_full_symbol_and_same_dollar_side_budget_block_more_risk():
    a,c,o,n=inputs()
    a['EURUSD']['positions']=[{'direction':1,'sl_risk_cash':500}]
    a['XAUUSD']['positions']=[{'direction':1,'sl_risk_cash':0}]
    rows=policy.allocate(a,c,o,n,NOW)['symbols']
    assert rows['EURUSD']['entry_budget_fraction']==0
    assert rows['XAUUSD']['entry_budget_fraction']==0


def test_correlated_entries_are_reduced_and_news_can_only_reduce_further():
    a,c,o,n=inputs()
    base=policy.allocate(a,c,o,n,NOW)['symbols']['EURUSD']
    assert base['correlation_risk_factor']==.5
    n['EURUSD']=.5
    reduced=policy.allocate(a,c,o,n,NOW)['symbols']['EURUSD']
    assert reduced['entry_budget_fraction']<=base['entry_budget_fraction']*.5+1e-10
    n['EURUSD']=0
    assert policy.allocate(a,c,o,n,NOW)['symbols']['EURUSD']['entry_budget_fraction']==0


def test_mismatched_account_outcomes_do_not_change_weights():
    a,c,o,n=inputs();o['XAUUSD']={str(i):dict(outcome('XAUUSD',i,2),account=8) for i in range(60)}
    assert policy.allocate(a,c,o,n,NOW)['symbols']['XAUUSD']['weight']==pytest.approx(1/3)


def test_fresh_exact_allocation_is_required_and_exit_plans_are_untouched():
    a,c,o,n=inputs();advice=policy.allocate(a,c,o,n,NOW)
    plan={'action':'open','strategy':'macd','direction':1}
    allowed=policy.constrain(plan,a['EURUSD'],advice,NOW)
    assert 0<allowed['risk_fraction']<=policy.ENTRY_CAP
    assert policy.constrain(plan,a['EURUSD'],advice,NOW+16)['status']=='waiting_for_portfolio_allocation'
    advice['symbols']['EURUSD']['executor_instance']='old'
    assert 'risk_fraction' not in policy.constrain(plan,a['EURUSD'],advice,NOW)
    close={'action':'close_tickets','tickets':[123]}
    assert policy.constrain(close,a['EURUSD'],{},NOW) is close


def test_oversized_allocation_is_rejected_before_transport():
    a,c,o,n=inputs();advice=policy.allocate(a,c,o,n,NOW)
    advice['symbols']['EURUSD']['entry_budget_fraction']=.1
    plan={'action':'open','strategy':'macd','direction':1}
    assert 'risk_fraction' not in policy.constrain(plan,a['EURUSD'],advice,NOW)


def test_random_allocations_never_exceed_remaining_gross_or_symbol_limits():
    rng=random.Random(37)
    for _ in range(100):
        a,c,o,n=inputs()
        for symbol in policy.SYMBOLS:
            a[symbol]['positions']=[{'direction':1,'sl_risk_cash':rng.uniform(0,150)}]
            n[symbol]=rng.choice([0,.5,1.])
        result=policy.allocate(a,c,o,n,NOW)
        total=sum(r['entry_budget_fraction'] for r in result['symbols'].values())
        assert total+result['open_risk_fraction']<=policy.PORTFOLIO_CAP+1e-10
        for row in result['symbols'].values():
            assert row['entry_budget_fraction']<=policy.ENTRY_CAP
            assert row['entry_budget_fraction']+row['used_risk_fraction']<=policy.SYMBOL_CAP+1e-10


def test_previous_protocol7_policy_requires_upgrade_before_larger_risk():
    a,c,o,n=inputs();a['EURUSD'].pop('risk_policy_version')
    assert not policy.allocate(a,c,o,n,NOW)['execution_ready']


def test_all_symbols_combined_cannot_add_more_than_half_percent():
    a,c,o,n=inputs()
    a['EURUSD']['positions']=[{'direction':1,'sl_risk_cash':499}]
    result=policy.allocate(a,c,o,n,NOW)
    assert sum(r['entry_budget_fraction'] for r in result['symbols'].values())<=.00001+1e-10
    a['EURUSD']['positions'][0]['sl_risk_cash']=500
    result=policy.allocate(a,c,o,n,NOW)
    assert all(r['entry_budget_fraction']==0 for r in result['symbols'].values())


def test_mixed_chart_timeframes_do_not_block_the_whole_demo_account():
    a,c,o,n=inputs();a['EURUSD'].update(period=5,period_seconds=300)
    result=policy.allocate(a,c,o,n,NOW)
    assert result['execution_ready']
    assert result['symbols']['EURUSD']['entry_budget_fraction']>0
    assert result['symbols']['EURUSD']['period']==5


def test_correlation_uses_matching_candle_ends_and_equal_return_spans():
    fast=[{'time':i*300,'close':100+math.sin(i*.11)+i*.02} for i in range(300)]
    slow=[{'time':fast[i]['time']-600,'close':fast[i]['close']} for i in range(2,300,3)]
    result=policy.correlation(slow,fast,900,300)
    assert result['samples']==96
    assert result['value']==pytest.approx(1)
