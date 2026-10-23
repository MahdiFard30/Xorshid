from email.utils import formatdate
import json
import pytest
from ultimate_khorshid.tools import headline_research as h

NOW=1_792_594_800

def feed(utc=NOW-60,url='https://www.federalreserve.gov/newsevents/pressreleases/test.htm'):
    return f'<rss><channel><item><title>Policy &amp; markets</title><description>Publisher summary</description><pubDate>{formatdate(utc,usegmt=True)}</pubDate><link>{url}</link></item></channel></rss>'.encode()


def result(ids):
    return {symbol:{'direction':1,'confidence':.8,'evidence_ids':ids,'thesis':'thesis','counterargument':'risk'} for symbol in h.SYMBOLS}


def test_parser_rejects_future_stale_untrusted_links_and_entity_expansion():
    assert len(h.parse_feed(feed(),h.FEEDS[0],NOW))==1
    assert not h.parse_feed(feed(NOW+1),h.FEEDS[0],NOW)
    assert not h.parse_feed(feed(NOW-h.MAX_AGE-1),h.FEEDS[0],NOW)
    assert not h.parse_feed(feed(url='https://attacker.invalid/a'),h.FEEDS[0],NOW)
    with pytest.raises(ValueError):h.parse_feed(b'<!DOCTYPE rss><rss/>',h.FEEDS[0],NOW)


def test_unsupported_citations_never_affect_trades():
    evidence=h.parse_feed(feed(),h.FEEDS[0],NOW)
    with pytest.raises(ValueError):h.validate(result(['made_up']),evidence,NOW)
    with pytest.raises(ValueError):h.validate(result([]),evidence,NOW)
    payload=result([evidence[0]['id']]);payload['XAUUSD']['direction']=True
    with pytest.raises(ValueError):h.validate(payload,evidence,NOW)


def test_refresh_is_rate_limited_and_ranking_is_bounded_and_expires(tmp_path):
    calls=[]
    def generate(messages):
        calls.append(messages)
        evidence=json.loads(messages[-1]['content'])
        return json.dumps(result([evidence[0]['id']]))
    report=h.refresh(tmp_path,NOW,lambda source:feed(),generate,article_fetch=lambda url:article())
    assert report['status']=='ready'
    assert h.adjustment(report,'XAUUSD',1,NOW)==0
    assert h.adjustment(report,'XAUUSD',-1,NOW)==0
    assert report['symbols']['XAUUSD']['direction']==0
    assert report['symbols']['XAUUSD']['grounding_status']=='missing_grounded_claims'
    assert h.adjustment(report,'XAUUSD',1,NOW+1800)==0
    h.refresh(tmp_path,NOW+10,lambda source:feed(),generate,article_fetch=lambda url:article())
    assert len(calls)==1
    assert 'balance' not in json.dumps(calls) and 'login' not in json.dumps(calls)


def test_network_or_model_failure_adds_no_entry_block(tmp_path):
    def fail(*a):raise RuntimeError('private credentials should not be persisted')
    report=h.refresh(tmp_path,NOW,fail,fail)
    assert report['status']=='no_fresh_evidence'
    assert h.adjustment(report,'XAUUSD',1,NOW)==0
    assert 'private credentials' not in json.dumps(report)
    report=h.refresh(tmp_path,NOW+901,lambda source:feed(),fail,article_fetch=lambda url:article())
    assert report['status']=='research_unavailable'
    assert h.adjustment(report,'XAUUSD',1,NOW+901)==0


def article():
    return ('<html><body><nav>Menu noise</nav><main><h1>Policy outlook</h1><p>'+
        'Inflation and monetary policy evidence. '*30+'</p><script>BAD_SCRIPT</script></main></body></html>').encode()


def test_full_article_text_reaches_model_without_navigation_or_script(tmp_path):
    def generate(messages):
        evidence=json.loads(messages[-1]['content'])
        text=evidence[0]['article']['text']
        assert 'Inflation and monetary policy' in text
        assert 'Menu noise' not in text and 'BAD_SCRIPT' not in text
        return result([evidence[0]['id']])
    report=h.refresh(tmp_path,NOW,lambda source:feed(),generate,article_fetch=lambda url:article())
    assert report['status']=='ready'
    assert report['evidence'][0]['article']['status']=='read'


def test_article_failure_is_explicit_and_does_not_invent_text(tmp_path):
    def fail(url):raise OSError('unavailable')
    def generate(messages):
        evidence=json.loads(messages[-1]['content'])
        assert evidence[0]['article']['status']=='unavailable'
        assert 'text' not in evidence[0]['article']
        return result([evidence[0]['id']])
    report=h.refresh(tmp_path,NOW,lambda source:feed(),generate,article_fetch=fail)
    assert report['status']=='ready'
