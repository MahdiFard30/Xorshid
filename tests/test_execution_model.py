import json
import pytest
from ultimate_khorshid.tools.execution_model import new_book, step, metrics
from ultimate_khorshid.tools.entry_protections import assess, constrain
from ultimate_khorshid.tools.demo_learning import Experience, NAMES
from ultimate_khorshid.tools.mt5_entry_policy import decision


def candle(time=10000, **changes):
    return dict({'time':time,'open':100.,'high':100.3,'low':99.8,'close':100.1,'spread':0},**changes)


def test_zero_spread_is_valid_but_crossed_or_expensive_quote_is_rejected():
    s={'positions':[],'algo_enabled':True,'tick_age_seconds':1,'blocking_positions':0,
       'total_orders':0,'max_positions':2,'bar_age_seconds':1,'entry_window_seconds':120,'bid':100.,'ask':100.}
    assert decision(s,{'macd':[1]},2,'macd')['action']=='open'
    for ask in (99.,100.21):
        assert decision({**s,'ask':ask},{'macd':[1]},2,'macd')['status']=='spread_too_large'


@pytest.mark.parametrize('side',[-1,1])
def test_stop_wins_ambiguous_candle_and_costs_are_charged(side):
    b=new_book()
    events=step(b,candle(high=104,low=96),side,2,.01)
    assert [e['kind'] for e in events]==['open','close']
    assert events[-1]['reason']=='stop' and events[-1]['r'] < -1
    assert b['equity']==pytest.approx(1+.0025*events[-1]['r'])
    assert metrics(b)['trades']==1


def test_quick_target_and_no_same_candle_reentry():
    b=new_book();step(b,candle(),1,2,.01)
    events=step(b,candle(10900,open=100.5,low=100.4,high=104),1,2,.01)
    assert [e['kind'] for e in events]==['close']
    assert events[0]['reason']=='quick_target' and 0<events[0]['r']<1


def test_gap_stop_precedes_opposite_signal():
    b=new_book();step(b,candle(),1,2,.01)
    events=step(b,candle(10900,open=95,low=94,high=96),-1,2,.01)
    assert events[0]['reason']=='gap_stop' and events[0]['r'] < -2


def test_future_news_cannot_select_staged_exit():
    b=new_book()
    events=step(b,candle(),1,2,.01,profile={'mode':'staged','known_at_server':10001,'expires_server':11800})
    assert events[0]['profile']=='quick'


def test_staged_partial_is_once_and_total_conserves_equity():
    b=new_book();step(b,candle(),1,2,.01,profile={'mode':'staged','known_at_server':9999,'expires_server':11800})
    events=step(b,candle(10060,open=102,low=101.9,high=102.3),1,2,.01)
    assert [e['kind'] for e in events]==['partial']
    assert b['position']['remaining']==.5
    events=step(b,candle(10120,open=102,low=101,high=102.2),1,2,.01)
    assert [e['kind'] for e in events]==['close']
    assert b['equity']==pytest.approx(1+.0025*events[-1]['r'])


def test_large_favorable_wick_cannot_trail_beyond_server_target():
    b=new_book();step(b,candle(),1,2,.01,profile={'mode':'staged','known_at_server':9999,'expires_server':11800})
    events=step(b,candle(10060,open=102,low=101.9,high=200),1,2,.01)
    assert events[-1]['r'] <= 2


def test_policy_mismatch_cannot_resume_old_paper_positions():
    b=new_book();b['exit_policy_version']=1
    with pytest.raises(ValueError): step(b,candle(),1,2,.01)


def snapshot(**changes):
    return dict({'login':7,'symbol':'EURUSD','generated_utc':10000,'broker_utc_offset_seconds':0,'period_seconds':900},**changes)


def outcomes(times,stop=True):
    return {str(i):{'account':7,'symbol':'EURUSD','position_id':i,'closed_complete':True,
        'closed_time_server':t,'net':-1,'exit_reasons':[4] if stop else []} for i,t in enumerate(times)}


def test_guards_are_durable_expire_and_never_block_exit():
    rows=outcomes([9000,9900]);s=snapshot()
    assert not assess(s,rows)['allow_entry']
    assert assess(snapshot(generated_utc=13500),rows)['allow_entry']
    assert constrain({'action':'close_tickets','tickets':[1]},s,rows)['action']=='close_tickets'
    rows['dup']=rows['1']
    assert assess(s,rows)['stop_count']==2
    rows['1']['closed_complete']=False;rows['dup']['closed_complete']=False
    assert assess(s,rows)['allow_entry']


def test_global_guard_does_not_use_other_accounts_or_future_closes():
    rows=outcomes([9000,9500,9900]);rows['0']['symbol']='XAUUSD'
    assert not assess(snapshot(),rows,True)['allow_entry']
    rows['0']['account']=8
    assert assess(snapshot(),rows,True)['allow_entry']
    rows['0']['account']=7;rows['0']['closed_time_server']=11000
    assert assess(snapshot(),rows,True)['allow_entry']


@pytest.mark.parametrize('changes',[{'period_seconds':None},{'period_seconds':90000},{'generated_utc':-1},{'broker_utc_offset_seconds':None}])
def test_unknown_guard_clock_pauses_entry(changes):
    assert not assess(snapshot(**changes),{})['allow_entry']


def test_paper_cooldown_uses_close_end_time():
    b=new_book();step(b,candle(high=104,period_seconds=900),1,2,.01)
    assert b['closed']==1
    assert step(b,candle(10900,period_seconds=900),1,2,.01)==[]
    assert step(b,candle(11800,period_seconds=900),1,2,.01)[0]['kind']=='open'


def test_learning_migration_archives_legacy_evidence_without_reusing_it(tmp_path):
    p=tmp_path/'experience.json';e=Experience(p)
    e.data['exit_policy_version']=1;e.data['stats'][NAMES[0]]['paper_n']=20
    e.data['stats'][NAMES[0]]['verified_demo_n']=3;e.data['verified_seen']=['old']
    e.save();m=Experience(p)
    assert m.data['stats'][NAMES[0]]['paper_n']==0
    assert m.data['stats'][NAMES[0]]['verified_demo_n']==0
    assert m.data['policy_archives'][0]['stats'][NAMES[0]]['paper_n']==20
    assert m.data['verified_seen']==['old']
    m.save();assert len(Experience(p).data['policy_archives'])==1


def test_offline_stop_hypotheses_keep_cash_risk_fixed_and_do_not_change_live_rules():
    from ultimate_khorshid.tools.exit_rules import STOP_ATR
    narrow=new_book();wide=new_book()
    step(narrow,candle(),1,2,.01,stop_atr=1)
    step(wide,candle(),1,2,.01,stop_atr=2)
    a,b=narrow['position'],wide['position']
    assert b['distance']==2*a['distance']
    assert a['risk_cash']==b['risk_cash']==.0025
    assert b['risk_cash']/b['distance']==a['risk_cash']/a['distance']/2
    assert STOP_ATR==1
    with pytest.raises(ValueError):step(wide,candle(10900),1,2,.01,stop_atr=1)


def test_exit_audit_distinguishes_failed_thesis_from_opposite_signal():
    position={'ticket':5,'direction':1,'comment':'KH:macd','bars_held':2,'progress_r':-.6}
    s={'positions':[position]}
    result=decision(s,{'macd':[0]},2,None)
    assert result['exit_details'][0]['reason']=='failed_thesis'
    result=decision(s,{'macd':[-1]},2,None)
    assert result['exit_details'][0]['reason']=='opposite_signal'
