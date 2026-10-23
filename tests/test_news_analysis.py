import copy

import pytest

from ultimate_khorshid.tools.news_analysis import analyze,reaction,risk_factor,SOURCE

NOW=1792497600


def inputs():
    bars=[]
    for i in range(100):
        utc=NOW-(100-i)*900
        close=100.+i*.01 if utc<NOW-3600 else 99.-i*.01
        bars.append({'time':utc+10800,'open':close,'close':close,'high':close+.05,'low':close-.05,'spread':2})
    snap={'period_seconds':900,'broker_utc_offset_seconds':10800,'bars':bars}
    event={'id':1,'revision':0,'title':'Test economic release','currency':'USD','importance':'High',
           'utc':NOW-3600,'actual':210.,'forecast':190.,'previous':180.,'unit':4,'multiplier':1,
           'potential_impact':'positive','source_url':'https://example.test/official'}
    native={'schema':1,'source':SOURCE,'generated_utc':NOW,'available':True,
            'currencies_complete':{'USD':True,'EUR':True,'JPY':True},'events':[event]}
    calendar={'fetched_utc':NOW,'events':[{'title':'Test','currency':'USD','impact':'High','utc':NOW+86400}]}
    return snap,native,calendar


def test_actual_forecast_comparison_and_price_confirmation():
    snap,native,cal=inputs()
    result=analyze('EURUSD',snap,cal,native,NOW)
    assert result['release_data_status']=='fresh'
    assert result['confirmed_direction']==-1
    evidence=result['evidence'][0]
    assert evidence['difference']==20
    assert evidence['market_reaction']['direction']==-1
    assert risk_factor(result,1)==.5 and risk_factor(result,-1)==1.


@pytest.mark.parametrize('change',[{'actual':None},{'forecast':None},{'actual':float('nan')}])
def test_missing_numbers_never_become_directional_evidence(change):
    snap,native,cal=inputs();native['events'][0].update(change)
    result=analyze('EURUSD',snap,cal,native,NOW)
    assert result['confirmed_direction']==0
    assert result['evidence'][0]['difference'] is None


def test_future_release_cannot_leak_actual_values_into_a_decision():
    snap,native,cal=inputs();native['events'][0]['utc']=NOW+100
    result=analyze('EURUSD',snap,cal,native,NOW)
    assert result['evidence']==[] and result['confirmed_direction']==0
    assert risk_factor(result,1)==0  # Native high-impact blackout still applies.


@pytest.mark.parametrize('change',[{'generated_utc':NOW-301},{'source':'unknown'},{'available':False},{'currencies_complete':{'USD':False}}])
def test_stale_or_unverified_native_feed_is_explicitly_unavailable(change):
    snap,native,cal=inputs();native.update(change)
    result=analyze('EURUSD',snap,cal,native,NOW)
    assert result['release_data_status']=='unavailable_or_incomplete'
    assert result['evidence']==[]


def test_unknown_broker_clock_does_not_confirm_a_market_reaction():
    snap,native,cal=inputs();snap.pop('broker_utc_offset_seconds')
    result=analyze('EURUSD',snap,cal,native,NOW)
    assert result['confirmed_direction']==0
    assert result['evidence'][0]['market_reaction']['status']=='broker_clock_unknown'


def test_only_completed_post_release_bars_are_used():
    snap,native,cal=inputs();native['events'][0]['utc']=NOW-300
    result=analyze('EURUSD',snap,cal,native,NOW)
    assert result['confirmed_direction']==0
    assert result['evidence'][0]['market_reaction']['status']=='waiting_for_complete_post_release_candle'


def test_conflicting_confirmed_news_reduces_risk_without_creating_an_entry():
    result={'schedule':{'allow_entry':True},'conflicting_events':True,'confirmed_direction':0}
    assert risk_factor(result,1)==.5 and risk_factor(result,-1)==.5


def test_repeated_release_is_not_counted_twice_and_equal_forecast_has_no_surprise():
    snap,native,cal=inputs();native['events']*=2
    result=analyze('EURUSD',snap,cal,native,NOW)
    assert len(result['evidence'])==1
    native['events'][0]['actual']=native['events'][0]['forecast']
    assert analyze('EURUSD',snap,cal,native,NOW)['confirmed_direction']==0


def test_revised_number_is_reported_but_not_used_to_explain_original_price_reaction():
    snap,native,cal=inputs();native['events'][0]['revision']=1
    result=analyze('EURUSD',snap,cal,native,NOW)
    assert result['evidence'][0]['difference']==20
    assert result['confirmed_direction']==0
