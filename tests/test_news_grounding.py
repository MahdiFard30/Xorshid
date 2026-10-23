import json
import pytest
from ultimate_khorshid.tools.news_grounding import ground,review
from ultimate_khorshid.tools import headline_research as h

QUOTE='The announced policy rate takes effect today.'


def evidence():
    return [{'id':'a','article':{'status':'read','text':QUOTE+' More context.'}}]


def row():
    return {'direction':1,'confidence':.8,'evidence_ids':['a'],'relevance':'direct','horizon':'short_term',
        'claims':[{'evidence_id':'a','quote':QUOTE,'fact':'The announced change takes effect today.'}]}


def test_exact_quote_is_required_and_cannot_be_invented_or_found_only_in_title():
    r=row();r['claims'][0]['quote']='This invented claim does not appear in the article.'
    assert ground(r,evidence())['direction']==0
    assert ground(row(),[{'id':'a','summary':QUOTE,'article':{'status':'unavailable'}}])['direction']==0
    assert ground(row(),evidence())['grounding_status']=='quotes_checked_awaiting_model_review'


@pytest.mark.parametrize('changes',[{'relevance':'indirect'},{'relevance':'unrelated'},{'horizon':'long_term'},{'horizon':'unknown'},{'claims':[]}])
def test_unsupported_link_or_timing_is_neutral_even_with_high_model_confidence(changes):
    r=ground({**row(),**changes},evidence())
    assert r['direction']==0 and r['confidence']<=.4
    assert r['proposed_direction']==1 and r['execution_eligible'] is False


def test_correct_quote_alone_is_not_enough_when_skeptical_review_disagrees_or_fails():
    rows={'EURUSD':ground(row(),evidence())}
    for verdict in ({},{'EURUSD':{'supported':False}},{'EURUSD':{'supported':True,'relevance':'direct','horizon':'long_term','reason':'Structural only'}}):
        assert review(rows,verdict)['EURUSD']['direction']==0
    verdict={'EURUSD':{'supported':True,'relevance':'direct','horizon':'short_term','reason':'Supported in supplied test evidence'}}
    result=review(rows,verdict)['EURUSD']
    assert result['direction']==1 and result['independently_fact_verified'] is False
    assert result['execution_eligible'] is False


def test_pipeline_calls_skeptical_reviewer_and_still_cannot_change_execution(tmp_path):
    from test_headline_research import feed,article,NOW
    calls=[]
    quote='Inflation and monetary policy evidence.'
    def generate(messages):
        calls.append(messages[0]['content'])
        if messages[0]['content'].startswith('SKEPTICAL_REVIEW:'):
            return {s:{'supported':False,'relevance':'indirect','horizon':'unknown','reason':'No evidence of intraday FX repricing'} for s in h.SYMBOLS}
        items=json.loads(messages[-1]['content']);ident=items[0]['id']
        return {s:{**row(),'evidence_ids':[ident],'claims':[{'evidence_id':ident,'quote':quote,'fact':'The article discusses policy evidence'}],
                   'thesis':'hypothesis','counterargument':'risk'} for s in h.SYMBOLS}
    report=h.refresh(tmp_path,NOW,lambda url:feed(),generate,article_fetch=lambda url:article())
    assert len(calls)==2 and report['execution_mode']=='report_only'
    assert all(r['direction']==0 for r in report['symbols'].values())
    assert h.adjustment(report,'EURUSD',1,NOW)==0
