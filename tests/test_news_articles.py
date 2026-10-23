import pytest
from ultimate_khorshid.tools.news_articles import read_article, check_url, PublisherRedirect

URL='https://www.ecb.europa.eu/press/example.html'


def test_extraction_excludes_navigation_and_prioritizes_main_article():
    body='<html><body><p>Other site content</p><main><p>'+'Policy evidence. '*60+'</p></main><footer>Footer</footer></body></html>'
    r=read_article(URL,lambda url:body.encode())
    assert r['status']=='read' and 'Policy evidence' in r['text']
    assert 'Other site content' not in r['text'] and 'Footer' not in r['text']


def test_article_length_and_download_size_are_bounded():
    body='<body><article><p>'+'Evidence. '*2000+'</p></article></body>'
    r=read_article(URL,lambda url:body.encode())
    assert r['truncated'] and len(r['text'])<=8000
    with pytest.raises(ValueError):read_article(URL,lambda url:b'x'*2_000_001)
    with pytest.raises(ValueError):read_article(URL,lambda url:b'<body>No text</body>')


@pytest.mark.parametrize('url',['http://www.ecb.europa.eu/a','https://attacker.invalid/a','https://www.ecb.europa.eu:8443/a','https://user@www.ecb.europa.eu/a','https://127.0.0.1/a'])
def test_nonpublisher_urls_and_redirects_are_rejected_before_request(url):
    with pytest.raises(ValueError):check_url(url)
    with pytest.raises(ValueError):PublisherRedirect().redirect_request(None,None,302,'',{},url)
