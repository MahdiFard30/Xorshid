from pathlib import Path
import random
import shutil
import subprocess

import pytest

from ultimate_khorshid.tools import managed_exits as policy
from ultimate_khorshid.tools.mt5_entry_policy import decision

NOW = 1792577000


def news(direction=1):
    return {'version': 1, 'updated_utc': NOW, 'release_data_status': 'fresh',
            'schedule': {'allow_entry': True}, 'confirmed_direction': direction,
            'conflicting_events': False, 'evidence': [
                {'revision': 0, 'utc': NOW-1200, 'observed_utc': NOW-10,
                 'actual': 4, 'forecast': 3, 'potential_symbol_direction': direction,
                 'interpretation': 'provider_hypothesis_matches_observed_price',
                 'market_reaction': {'status': 'observed', 'direction': direction,
                                     'change_atr': direction*.6, 'last_closed_bar_utc': NOW-100}}]}


def test_only_fresh_corroborated_news_can_receive_a_bounded_tilt():
    strong = policy.opportunity(news(), 1, NOW)
    assert strong['mode'] == 'staged' and strong['weight_multiplier'] == 1.5
    assert NOW+120 <= strong['expires_utc'] <= NOW+1800
    assert policy.opportunity(news(-1), -1, NOW)['mode'] == 'staged'
    assert policy.opportunity(news(), -1, NOW)['mode'] == 'quick'
    for change in ({'release_data_status': 'unavailable_or_incomplete'},
                   {'conflicting_events': True}, {'updated_utc': NOW-16},
                   {'evidence': []}, {'schedule': {'allow_entry': False}}):
        assert policy.opportunity({**news(), **change}, 1, NOW)['mode'] == 'quick'


@pytest.mark.parametrize('change', [
    {'actual': None}, {'forecast': None}, {'revision': 1}, {'utc': NOW+1},
    {'utc': NOW-3601}, {'observed_utc': NOW-301}, {'actual': 3},
    {'market_reaction': {'status': 'waiting_for_complete_post_release_candle'}},
    {'market_reaction': {'status': 'observed', 'direction': 1, 'change_atr': -.8, 'last_closed_bar_utc': NOW-100}},
])
def test_missing_future_revised_or_contradictory_evidence_does_not_increase_size(change):
    analysis = news()
    analysis['evidence'][0].update(change)
    assert policy.opportunity(analysis, 1, NOW)['weight_multiplier'] == 1


def test_smaller_stop_reduces_cash_risk_without_automatically_increasing_volume():
    plan = {'action': 'open', 'direction': 1, 'risk_fraction': .002, 'symbol_cap_fraction': .003}
    result = policy.entry_profile(plan, {'period_seconds': 900}, {}, NOW)
    old_volume_proxy = plan['risk_fraction'] / 2
    new_volume_proxy = result['risk_fraction'] / result['stop_atr']
    assert new_volume_proxy == pytest.approx(old_volume_proxy)
    assert result['risk_fraction'] == .001
    assert result['exit_profile'] == 'quick' and result['target_r'] == 1.
    strong = policy.entry_profile(plan, {'period_seconds': 900}, news(), NOW)
    assert strong['exit_profile'] == 'staged' and strong['target_r'] == 2
    close = {'action': 'close_tickets', 'tickets': [1]}
    assert policy.entry_profile(close, {}, {}, NOW) is close


def test_news_tilt_redistributes_without_raising_total_or_symbol_caps():
    from test_portfolio_policy import inputs, NOW as ALLOCATION_NOW
    from ultimate_khorshid.tools.portfolio_policy import allocate, PORTFOLIO_CAP
    snapshots, candidates, outcomes, factors = inputs()
    evidence = news()
    delta = ALLOCATION_NOW-NOW
    evidence['updated_utc'] += delta
    for item in evidence['evidence']:
        item['utc'] += delta; item['observed_utc'] += delta
        item['market_reaction']['last_closed_bar_utc'] += delta
    base = allocate(snapshots, candidates, outcomes, factors, ALLOCATION_NOW)
    tilted = allocate(snapshots, candidates, outcomes, factors, ALLOCATION_NOW, {'XAUUSD': evidence})
    assert tilted['symbols']['XAUUSD']['weight'] > base['symbols']['XAUUSD']['weight']
    assert tilted['symbols']['XAUUSD']['entry_budget_fraction'] > base['symbols']['XAUUSD']['entry_budget_fraction']
    assert sum(r['entry_budget_fraction'] for r in tilted['symbols'].values()) <= PORTFOLIO_CAP
    snapshots['EURUSD']['executor_version'] = 7
    assert not allocate(snapshots, candidates, outcomes, factors, ALLOCATION_NOW)['execution_ready']


def test_losing_position_with_failed_signal_exits_at_half_risk_after_two_bars():
    position = {'ticket': 5, 'direction': 1, 'comment': 'KH:macd', 'bars_held': 2, 'progress_r': -.51}
    snapshot = {'positions': [position], 'algo_enabled': False}
    assert decision(snapshot, {'macd': [0]}, 1, None)['tickets'] == [5]
    for change in ({'progress_r': -.2}, {'bars_held': 1}):
        snapshot['positions'] = [{**position, **change}]
        assert decision(snapshot, {'macd': [0]}, 1, None)['status'] == 'algo_disabled'
    snapshot['positions'] = [position]
    assert decision(snapshot, {'macd': [1]}, 1, None)['status'] == 'algo_disabled'


@pytest.fixture(scope='module')
def native(tmp_path_factory):
    compiler = shutil.which('g++')
    if not compiler:
        pytest.skip('C++ compiler required')
    folder = tmp_path_factory.mktemp('managed-exits')
    header = Path(__file__).resolve().parents[1]/'mt5/RestartPolicy.mqh'
    source = folder/'policy.cpp'
    source.write_text('#include <iostream>\n#include <iomanip>\n#include <cstdlib>\n#include "'+str(header)+'"\n'
        'int main(int n,char**v){std::cout<<std::setprecision(17);std::string mode=v[1];'
        'if(mode=="exit")std::cout<<ManagedExitAction(atof(v[2]),atoi(v[3]),atoi(v[4]),atof(v[5]),atof(v[6]));'
        'if(mode=="volume")std::cout<<ManagedPartialVolume(atof(v[2]),atof(v[3]),atof(v[4]),atof(v[5]));'
        'if(mode=="stop")std::cout<<ManagedStop(atoi(v[2]),atof(v[3]),atof(v[4]),atof(v[5]),atof(v[6]),atof(v[7]),atof(v[8]));'
        'if(mode=="guard")std::cout<<EntryPauseUntil(atol(v[2]),atol(v[3]),atol(v[4]),atoi(v[5]),atol(v[6]),atoi(v[7]),atol(v[8]));}')
    binary = folder/'policy'
    subprocess.run([compiler, str(source), '-o', str(binary)], capture_output=True, check=True)
    def run(mode, *args):
        return float(subprocess.run([str(binary), mode, *map(str, args)], capture_output=True, text=True, check=True).stdout)
    return run


def test_native_staged_exit_occurs_once_and_weak_profile_exits_sooner(native):
    assert native('exit', .49, 0, 0, 49, 10) == 0
    assert native('exit', .5, 0, 0, 50, 10) == 0
    assert native('exit', 1., 0, 0, 100, 10) == 1
    assert native('exit', .8, 1, 0, 80, 10) == 0
    assert native('exit', 1, 1, 0, 100, 10) == 2
    assert native('exit', 1.3, 1, 1, 130, 10) == 0
    assert native('exit', 2, 1, 1, 200, 10) == 1
    assert native('exit', 2, 1, 0, 200, 10) == 1  # Gap skips the first stage.
    assert native('exit', .6, 0, 0, -1, 10) == 0
    assert native('exit', float('nan'), 1, 0, 100, 10) == 0


def test_native_partial_volume_cannot_reverse_or_repeat_half_close(native):
    assert native('volume', .11, .11, .01, .01) == pytest.approx(.05)
    assert native('volume', .1, .1, .01, .01) == pytest.approx(.05)
    assert native('volume', .1, .05, .01, .01) == 0
    assert native('volume', .01, .01, .01, .01) == 0
    assert native('volume', 1, 1, .01, 0) == 0


def test_native_trailing_is_monotone_for_both_directions_and_respects_broker_distance(native):
    rng = random.Random(72)
    for side in (-1, 1):
        old = 100-side*2
        for _ in range(40):
            price = 100+side*rng.uniform(2, 10)
            result = native('stop', side, 100, price, 2, old, .01, .2)
            if result:
                assert side*(result-old) > 0
                assert side*(price-result) >= .2-1e-9
                assert side*(result-100) >= 0
                old = result
    assert native('stop', 1, 100, 101, 2, 98, .01, .2) == 0
    assert native('stop', 1, 100, 103, 2, 98, .01, 2) == 0


def test_native_entry_protection_matches_durable_python_guards(native):
    from ultimate_khorshid.tools.entry_protections import assess
    rng=random.Random(53)
    for _ in range(80):
        now=100000;period=900;n=rng.randrange(5)
        closes=sorted(now-rng.randrange(7201) for i in range(n))
        rows={str(i):{'account':7,'symbol':'EURUSD','position_id':i,'closed_complete':True,
            'closed_time_server':t,'net':-1,'exit_reasons':[4]} for i,t in enumerate(closes)}
        snapshot={'login':7,'symbol':'EURUSD','generated_utc':now,'broker_utc_offset_seconds':0,'period_seconds':period}
        result=assess(snapshot,rows)
        expected=result['blocked_until_server'] or 0
        assert native('guard',now,period,max(closes,default=0),n,max(closes,default=0),0,0)==expected
    assert native('guard',10000,0,0,0,0,0,0)==-1
    assert native('guard',10000,900,0,0,0,3,9900)==13500
