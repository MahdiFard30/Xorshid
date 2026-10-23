import copy
import pytest
from ultimate_khorshid.tools.mt5_entry_policy import first_positive_exit


def sample(profit=5):
    return {'demo':True,'algo_enabled':True,'tick_age_seconds':0,
            'positions':[{'identifier':10,'ticket':11,'comment':'KH:rsi_rebound','profit':profit}],
            'deals':[{'ticket':1,'position_id':10,'entry':0,'volume':1.,'profit':0.,
                      'commission':-2.,'swap':0.,'fee':0.}]}


def test_first_positive_accounts_for_entry_and_estimated_exit_charges():
    s=sample();before=copy.deepcopy(s);p=first_positive_exit(s)
    assert p['tickets']==[11] and p['exit_details'][0]['estimated_net']==1
    assert p['exit_details'][0]['live_swap_available'] is False
    assert p['exit_details'][0]['final_net_guaranteed'] is False
    assert s==before
    assert first_positive_exit(sample(4)) is None
    assert first_positive_exit(sample(-2)) is None


@pytest.mark.parametrize('field,value',[('demo',False),('algo_enabled',False),('tick_age_seconds',3)])
def test_unavailable_execution_cannot_trigger_profit_close(field,value):
    s=sample();s[field]=value
    assert first_positive_exit(s) is None


def test_incomplete_costs_and_unrelated_positions_do_not_create_invented_net_profit():
    s=sample();del s['deals'][0]['fee']
    assert first_positive_exit(s) is None
    s=sample();s['deals']=[]
    assert first_positive_exit(s) is None
    s=sample();s['positions'][0]['comment']='manual'
    assert first_positive_exit(s) is None


def test_known_live_swap_and_realized_costs_are_included():
    s=sample();s['positions'][0]['swap']=-2
    assert first_positive_exit(s) is None
    s['positions'][0]['swap']=0
    s['deals'].append(dict(s['deals'][0],ticket=2,entry=1,volume=.5,profit=1.,commission=-1.))
    assert first_positive_exit(s)['exit_details'][0]['estimated_net']==2
