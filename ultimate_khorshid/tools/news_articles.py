"""Bounded extraction of public central-bank article text; no trading calls."""
import hashlib
from html.parser import HTMLParser
import shutil
import subprocess
from urllib.parse import urlsplit
import urllib.request

HOSTS = {'www.federalreserve.gov','www.ecb.europa.eu'}
LIMIT = 8000


def check_url(url):
    p=urlsplit(url)
    if p.scheme!='https' or p.hostname not in HOSTS or p.port not in (None,443) or p.username or p.password:
        raise ValueError('Article URL outside configured publishers')


class PublisherRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[];self.parts={0:[],1:[],2:[]}

    def handle_starttag(self,tag,attrs):
        attrs=dict(attrs)
        parent=self.stack[-1] if self.stack else ('',0,False)
        level=2 if tag in ('main','article') or attrs.get('id')=='article' else 1 if tag=='body' else 0
        level=max(level,parent[1])
        blocked=parent[2] or tag in ('script','style','nav','footer','header','aside','form','noscript')
        if not blocked and tag in ('p','h1','h2','h3','li','br','div'):self.parts[level].append('\n')
        if tag not in ('area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'):
            self.stack.append((tag,level,blocked))

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                if not self.stack[i][2]:self.parts[self.stack[i][1]].append('\n')
                del self.stack[i:];break

    def handle_data(self,text):
        if self.stack and not self.stack[-1][2]:self.parts[self.stack[-1][1]].append(text)

    def text(self):
        for level in (2,1):
            text=' '.join(' '.join(self.parts[level]).split())
            if len(text)>=300:return text
        raise ValueError('Article text unavailable')


def read_article(url,fetch=None):
    check_url(url)
    if fetch is None:
        opener=urllib.request.build_opener(PublisherRedirect())
        request=urllib.request.Request(url,headers={'User-Agent':'KhorshidNewsResearch/1.1'})
        with opener.open(request,timeout=8) as response:
            check_url(response.geturl());raw=response.read(2_000_001)
    else:raw=fetch(url)
    if len(raw)>2_000_000:raise ValueError('Article exceeds size limit')
    if raw.startswith(b'%PDF'):
        tool=shutil.which('pdftotext')
        if not tool:raise ValueError('PDF reader unavailable')
        result=subprocess.run([tool,'-f','1','-l','6','-','-'],input=raw,capture_output=True,timeout=5,check=True)
        text=' '.join(result.stdout.decode('utf-8',errors='replace').split())
        scope='PDF first six pages'
    else:
        parser=ArticleText();parser.feed(raw.decode('utf-8',errors='replace'));text=parser.text()
        scope='article HTML'
    if len(text)<300:raise ValueError('Insufficient article text')
    truncated=len(text)>LIMIT
    excerpt=text[:6000]+'\n[... length limit ...]\n'+text[-1900:] if truncated else text
    return {'text':excerpt,'text_sha256':hashlib.sha256(text.encode()).hexdigest(),
            'extracted_characters':len(text),'truncated':truncated,'scope':scope,'status':'read'}
