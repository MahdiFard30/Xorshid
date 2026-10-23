import json
import sqlite3
from ultimate_khorshid.tools.trade_audit import audit_symbol,aggregate,news_comparison
from ultimate_khorshid.tools.trade_memory import TradeMemory


def setup(root,exits):
    folder=root/'.khorshid-multi/EURUSD';folder.mkdir(parents=True)
    state={'id':'run','login':7,'symbol':'EURUSD','currency':'USD','period':5,
           'started_utc':100,'last_snapshot_utc':500,'balance':100,'equity':100}
    (folder/'state.json').write_text(json.dumps(state))
    entry={'ticket':1,'order':10,'position_id':10,'entry':0,'volume':1.,'time':200,
           'price':1.1,'comment':'KH:macd','net':0,'profit':0,'commission':0,'swap':0,'fee':0}
    deals=[entry]+[dict(entry,ticket=i+2,order=20+i,entry=1,volume=volume,time=300+i,reason=5,net=net,profit=net) for i,(volume,net) in enumerate(exits)]
    with sqlite3.connect(folder/'journal.sqlite') as con:
        con.execute('CREATE TABLE deals(run_id TEXT,data TEXT)')
        con.executemany('INSERT INTO deals VALUES (?,?)',[('run',json.dumps(d)) for d in deals])
    memory=TradeMemory(folder/'trade_memory.sqlite')
    context={'run_id':'run','request_id':99,'recorded_utc':150,'action':'open','direction':1,
             'decision':{'selected':'macd','learning':{'score_details':{'macd':{'demo_results':0,'exploration_bonus':.2}}}},'recent_closed_bars':[]}
    with memory.connect() as con:
        for d in deals:con.execute('INSERT INTO observations VALUES (?,?,?,?)',(7,d['ticket'],'EURUSD',json.dumps(d)))
        con.execute('INSERT INTO intents VALUES (?,?,?,?,?)',(7,99,'EURUSD',5,json.dumps(context)))
        con.execute('INSERT INTO acknowledgements VALUES (?,?,?)',(7,99,json.dumps({'status':'executed','order':10})))
    return folder


def test_partial_exit_is_not_a_completed_trade_and_inputs_are_not_mutated(tmp_path):
    folder=setup(tmp_path,[(.4,4)])
    before={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}
    summary,trades,bars=audit_symbol(tmp_path,'EURUSD')
    assert summary['closed']==0 and summary['last_known_unclosed']==1
    assert not trades[0]['closed_complete'] and trades[0]['context_linked']
    assert before=={p.name:p.read_bytes() for p in folder.iterdir() if p.is_file()}


def test_completed_partial_legs_are_counted_once_and_reconcile_net(tmp_path):
    setup(tmp_path,[(.4,4),(.6,6)])
    summary,trades,_=audit_symbol(tmp_path,'EURUSD')
    assert summary['closed']==1 and summary['net']==10
    assert trades[0]['context_linked'] and trades[0]['exploration_used']
    assert trades[0]['normalized_reward'] is None # no fabricated SL-risk denominator
    assert aggregate(trades)['net']==10


def test_missing_ack_cannot_be_linked_by_nearby_time_or_symbol(tmp_path):
    folder=setup(tmp_path,[(1,10)])
    with sqlite3.connect(folder/'trade_memory.sqlite') as con:
        con.execute('UPDATE acknowledgements SET data=?',(json.dumps({'status':'executed','order':999}),))
    summary,trades,_=audit_symbol(tmp_path,'EURUSD')
    assert not trades[0]['context_linked'] and not trades[0]['learning_eligible']
    assert 'entry_decision_link_unavailable' in trades[0]['evidence_problems']


def test_news_counterfactual_reconstructs_ranking_but_not_returns():
    decision={'selected':'macd','learning':{'candidates':{'macd':.2,'roc':.1},'news_adjustments':{'macd':.15}}}
    r=news_comparison(decision)
    assert r['without_news_selected']=='roc' and r['selection_changed']
    assert r['profitability_effect']=='not_identifiable_from_filled_orders_alone'
    decision['learning']['candidates']['roc']=.05
    assert news_comparison(decision)['status']=='unresolved_without_recorded_tie_break'
